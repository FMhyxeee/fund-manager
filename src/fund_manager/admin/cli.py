"""Action-oriented CLI for local fund-manager operations."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, cast
from uuid import uuid4

from sqlalchemy.orm import Session

from fund_manager.agents.workflows.daily_decision import DailyDecisionWorkflow
from fund_manager.agents.workflows.strategy_debate import StrategyDebateWorkflow
from fund_manager.agents.workflows.weekly_review import WeeklyReviewWorkflow
from fund_manager.core.serialization import serialize_for_json
from fund_manager.core.services import (
    DecisionFeedbackError,
    DecisionFeedbackService,
    FundDataSyncService,
    IncompletePortfolioSnapshotError,
    PolicyService,
    PortfolioNotFoundError,
    PortfolioService,
)
from fund_manager.storage.db import get_session_factory
from fund_manager.storage.models import DecisionFeedbackStatus, DecisionRun
from fund_manager.storage.repo import (
    DecisionRunRepository,
    FundMasterRepository,
    PortfolioPolicyRepository,
    PortfolioPolicyTargetCreate,
    PortfolioRepository,
)


CommandHandler = Callable[[argparse.Namespace, Session], Any]


@dataclass(frozen=True)
class PolicyTargetSpec:
    """CLI-friendly representation of one policy target definition."""

    fund_code: str
    target_weight_ratio: Decimal
    min_weight_ratio: Decimal | None = None
    max_weight_ratio: Decimal | None = None
    add_allowed: bool = True
    trim_allowed: bool = True


class CommandError(Exception):
    """Raised when a CLI action cannot be completed as requested."""


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _parse_decimal(value: str) -> Decimal:
    return Decimal(value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run action-oriented fund-manager admin commands.",
    )
    resource_subparsers = parser.add_subparsers(dest="resource", required=True)

    _build_policy_commands(resource_subparsers)
    _build_decision_commands(resource_subparsers)
    _build_workflow_commands(resource_subparsers)

    return parser


def _build_policy_commands(
    resource_subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    policy_parser = resource_subparsers.add_parser("policy", help="Read or append portfolio policies.")
    policy_subparsers = policy_parser.add_subparsers(dest="action", required=True)

    show_parser = policy_subparsers.add_parser("show", help="Show the active policy for one date.")
    show_parser.add_argument("--portfolio-id", type=int, required=True)
    show_parser.add_argument("--as-of-date", type=_parse_date, default=None)
    show_parser.set_defaults(handler=_handle_policy_show)

    create_parser = policy_subparsers.add_parser("create", help="Append one policy snapshot.")
    create_parser.add_argument("--portfolio-id", type=int, required=True)
    create_parser.add_argument("--policy-name", required=True)
    create_parser.add_argument("--effective-from", type=_parse_date, required=True)
    create_parser.add_argument("--effective-to", type=_parse_date, default=None)
    create_parser.add_argument("--rebalance-threshold-ratio", type=_parse_decimal, required=True)
    create_parser.add_argument("--max-single-position-weight-ratio", type=_parse_decimal, default=None)
    create_parser.add_argument("--created-by", default=None)
    create_parser.add_argument("--notes", default=None)
    create_parser.add_argument("--run-id", default=None)
    create_parser.add_argument(
        "--target",
        action="append",
        required=True,
        help=(
            "Policy target spec, repeated once per fund. "
            "Format: fund_code=000001,target_weight_ratio=0.50[,min_weight_ratio=0.45]"
        ),
    )
    create_parser.set_defaults(handler=_handle_policy_create)


def _build_decision_commands(
    resource_subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    decision_parser = resource_subparsers.add_parser("decision", help="Manage decision runs.")
    decision_subparsers = decision_parser.add_subparsers(dest="action", required=True)

    list_parser = decision_subparsers.add_parser("list", help="List recent decision runs.")
    list_parser.add_argument("--portfolio-id", type=int, default=None)
    list_parser.add_argument("--decision-date", type=_parse_date, default=None)
    list_parser.add_argument("--limit", type=int, default=20)
    list_parser.set_defaults(handler=_handle_decision_list)

    show_parser = decision_subparsers.add_parser("show", help="Show one decision run.")
    show_parser.add_argument("--decision-run-id", type=int, required=True)
    show_parser.set_defaults(handler=_handle_decision_show)

    run_parser = decision_subparsers.add_parser("run", help="Run one daily decision workflow.")
    run_parser.add_argument("--portfolio-id", type=int, required=True)
    run_parser.add_argument("--decision-date", type=_parse_date, default=None)
    run_parser.add_argument("--trigger-source", default="cli")
    run_parser.set_defaults(handler=_handle_decision_run)

    feedback_parser = decision_subparsers.add_parser(
        "feedback",
        help="Record manual feedback for one deterministic decision action.",
    )
    feedback_parser.add_argument("--decision-run-id", type=int, required=True)
    feedback_parser.add_argument("--action-index", type=int, required=True)
    feedback_parser.add_argument(
        "--feedback-status",
        choices=[status.value for status in DecisionFeedbackStatus],
        required=True,
    )
    feedback_parser.add_argument("--feedback-date", type=_parse_date, default=None)
    feedback_parser.add_argument("--note", default=None)
    feedback_parser.add_argument("--created-by", default=None)
    feedback_parser.add_argument(
        "--no-reconcile-existing-transactions",
        action="store_true",
        help="Do not try to link existing transactions to this feedback row.",
    )
    feedback_parser.set_defaults(handler=_handle_decision_feedback)


def _build_workflow_commands(
    resource_subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    workflow_parser = resource_subparsers.add_parser("workflow", help="Run manual workflows.")
    workflow_subparsers = workflow_parser.add_subparsers(dest="action", required=True)

    run_parser = workflow_subparsers.add_parser("run", help="Run one workflow by name.")
    workflow_run_subparsers = run_parser.add_subparsers(dest="workflow_name", required=True)

    daily_snapshot_parser = workflow_run_subparsers.add_parser(
        "daily-snapshot",
        help="Run daily snapshot sync + snapshot persistence.",
    )
    daily_snapshot_parser.add_argument("--portfolio-id", type=int, required=True)
    daily_snapshot_parser.add_argument("--as-of-date", type=_parse_date, default=None)
    daily_snapshot_parser.add_argument("--trigger-source", default="cli")
    daily_snapshot_parser.set_defaults(handler=_handle_workflow_run_daily_snapshot)

    daily_decision_parser = workflow_run_subparsers.add_parser(
        "daily-decision",
        help="Run the daily decision workflow.",
    )
    daily_decision_parser.add_argument("--portfolio-id", type=int, required=True)
    daily_decision_parser.add_argument("--decision-date", type=_parse_date, default=None)
    daily_decision_parser.add_argument("--trigger-source", default="cli")
    daily_decision_parser.set_defaults(handler=_handle_workflow_run_daily_decision)

    weekly_review_parser = workflow_run_subparsers.add_parser(
        "weekly-review",
        help="Run the weekly review workflow.",
    )
    weekly_review_parser.add_argument("--portfolio-id", type=int, required=True)
    weekly_review_parser.add_argument("--period-start", type=_parse_date, default=None)
    weekly_review_parser.add_argument("--period-end", type=_parse_date, default=None)
    weekly_review_parser.add_argument("--trigger-source", default="cli")
    weekly_review_parser.set_defaults(handler=_handle_workflow_run_weekly_review)

    strategy_parser = workflow_run_subparsers.add_parser(
        "monthly-strategy-debate",
        help="Run the monthly strategy debate workflow.",
    )
    strategy_parser.add_argument("--portfolio-id", type=int, required=True)
    strategy_parser.add_argument("--period-start", type=_parse_date, default=None)
    strategy_parser.add_argument("--period-end", type=_parse_date, default=None)
    strategy_parser.add_argument("--trigger-source", default="cli")
    strategy_parser.set_defaults(handler=_handle_workflow_run_monthly_strategy_debate)


def _handle_policy_show(args: argparse.Namespace, session: Session) -> dict[str, Any]:
    _require_portfolio(session, args.portfolio_id)
    policy = PolicyService(session).get_active_policy(
        portfolio_id=args.portfolio_id,
        as_of_date=args.as_of_date or date.today(),
    )
    if policy is None:
        raise CommandError("Active policy not found.")
    return cast(dict[str, Any], serialize_for_json(policy))


def _handle_policy_create(args: argparse.Namespace, session: Session) -> dict[str, Any]:
    _require_portfolio(session, args.portfolio_id)
    targets = _resolve_policy_targets(session, args.target)
    policy_repo = PortfolioPolicyRepository(session)
    policy_repo.append(
        portfolio_id=args.portfolio_id,
        policy_name=args.policy_name,
        effective_from=args.effective_from,
        effective_to=args.effective_to,
        rebalance_threshold_ratio=args.rebalance_threshold_ratio,
        max_single_position_weight_ratio=args.max_single_position_weight_ratio,
        created_by=args.created_by,
        notes=args.notes,
        run_id=args.run_id,
        targets=targets,
    )
    session.commit()

    policy = PolicyService(session).get_active_policy(
        portfolio_id=args.portfolio_id,
        as_of_date=args.effective_from,
    )
    if policy is None:
        raise CommandError("Created policy could not be reloaded.")
    return cast(dict[str, Any], serialize_for_json(policy))


def _handle_decision_list(args: argparse.Namespace, session: Session) -> list[dict[str, Any]]:
    decision_runs = DecisionRunRepository(session).list_recent(
        portfolio_id=args.portfolio_id,
        decision_date=args.decision_date,
        limit=args.limit,
    )
    return [_build_decision_run_summary_payload(decision_run) for decision_run in decision_runs]


def _handle_decision_show(args: argparse.Namespace, session: Session) -> dict[str, Any]:
    decision_run = DecisionRunRepository(session).get_detail_by_id(args.decision_run_id)
    if decision_run is None:
        raise CommandError("Decision run not found.")
    return _build_decision_run_detail_payload(decision_run)


def _handle_decision_run(args: argparse.Namespace, session: Session) -> dict[str, Any]:
    return _run_daily_decision_payload(
        session,
        portfolio_id=args.portfolio_id,
        decision_date=args.decision_date or date.today(),
        trigger_source=args.trigger_source,
    )


def _handle_decision_feedback(args: argparse.Namespace, session: Session) -> dict[str, Any]:
    result = DecisionFeedbackService(session).record_feedback(
        decision_run_id=args.decision_run_id,
        action_index=args.action_index,
        feedback_status=DecisionFeedbackStatus(args.feedback_status),
        feedback_date=args.feedback_date,
        note=args.note,
        created_by=args.created_by,
        reconcile_existing_transactions=not args.no_reconcile_existing_transactions,
    )
    session.commit()
    payload = cast(dict[str, Any], serialize_for_json(result))
    payload["message"] = (
        f"Recorded {result.feedback_status.value} feedback for action {result.action_index}."
    )
    return payload


def _handle_workflow_run_daily_snapshot(args: argparse.Namespace, session: Session) -> dict[str, Any]:
    _require_portfolio(session, args.portfolio_id)
    as_of_date = args.as_of_date or date.today()
    workflow_name = "daily_snapshot"
    run_id = f"daily-snapshot-{as_of_date:%Y%m%d}-{uuid4().hex[:8]}"

    sync_result = FundDataSyncService(session).sync_portfolio_funds(
        args.portfolio_id,
        as_of_date=as_of_date,
    )
    session.commit()
    snapshot = PortfolioService(session).save_portfolio_snapshot(
        args.portfolio_id,
        as_of_date=as_of_date,
        run_id=run_id,
        workflow_name=workflow_name,
    )
    session.commit()

    return {
        "run_id": run_id,
        "workflow_name": workflow_name,
        "portfolio_id": args.portfolio_id,
        "as_of_date": as_of_date,
        "sync": serialize_for_json(sync_result.to_dict()),
        "snapshot": serialize_for_json(snapshot.to_dict()),
        "message": f"Daily snapshot completed. Run ID: {run_id}",
    }


def _handle_workflow_run_daily_decision(args: argparse.Namespace, session: Session) -> dict[str, Any]:
    return _run_daily_decision_payload(
        session,
        portfolio_id=args.portfolio_id,
        decision_date=args.decision_date or date.today(),
        trigger_source=args.trigger_source,
    )


def _handle_workflow_run_weekly_review(args: argparse.Namespace, session: Session) -> dict[str, Any]:
    _require_portfolio(session, args.portfolio_id)
    period_start, period_end = _resolve_period_bounds(
        period_start=args.period_start,
        period_end=args.period_end,
        default_span_days=7,
    )
    result = WeeklyReviewWorkflow(session).run(
        portfolio_id=args.portfolio_id,
        period_start=period_start,
        period_end=period_end,
        trigger_source=args.trigger_source,
    )
    return {
        "run_id": result.run_id,
        "workflow_name": result.workflow_name,
        "portfolio_id": result.portfolio_id,
        "period_start": result.period_start,
        "period_end": result.period_end,
        "report_record_id": result.report_record_id,
        "message": f"Weekly review completed. Run ID: {result.run_id}",
    }


def _handle_workflow_run_monthly_strategy_debate(
    args: argparse.Namespace,
    session: Session,
) -> dict[str, Any]:
    _require_portfolio(session, args.portfolio_id)
    period_end = args.period_end or date.today()
    period_start = args.period_start or period_end.replace(day=1)
    if period_start > period_end:
        raise ValueError("period_start cannot be later than period_end.")

    result = StrategyDebateWorkflow(session).run(
        portfolio_id=args.portfolio_id,
        period_start=period_start,
        period_end=period_end,
        trigger_source=args.trigger_source,
    )
    return {
        "run_id": result.run_id,
        "workflow_name": result.workflow_name,
        "portfolio_id": result.portfolio_id,
        "period_start": result.period_start,
        "period_end": result.period_end,
        "strategy_proposal_record_id": result.strategy_proposal_record_id,
        "final_decision": result.judge_output.final_judgment,
        "confidence_score": float(result.judge_output.confidence_score),
        "strategy_output": serialize_for_json(asdict(result.strategy_output)),
        "challenger_output": serialize_for_json(asdict(result.challenger_output)),
        "judge_output": serialize_for_json(asdict(result.judge_output)),
        "message": f"Monthly strategy debate completed. Run ID: {result.run_id}",
    }


def _run_daily_decision_payload(
    session: Session,
    *,
    portfolio_id: int,
    decision_date: date,
    trigger_source: str,
) -> dict[str, Any]:
    _require_portfolio(session, portfolio_id)
    result = DailyDecisionWorkflow(session).run(
        portfolio_id=portfolio_id,
        decision_date=decision_date,
        trigger_source=trigger_source,
    )
    decision_payload = serialize_for_json(result.decision.to_dict())
    return {
        "run_id": result.run_id,
        "workflow_name": result.workflow_name,
        "portfolio_id": result.portfolio_id,
        "decision_date": result.decision_date,
        "decision_run_id": result.decision_run_record_id,
        "final_decision": result.decision.final_decision,
        "action_count": result.decision.action_count,
        "decision": decision_payload,
        "message": f"Daily decision completed. Run ID: {result.run_id}",
    }


def _resolve_period_bounds(
    *,
    period_start: date | None,
    period_end: date | None,
    default_span_days: int,
) -> tuple[date, date]:
    resolved_period_end = period_end or date.today()
    resolved_period_start = period_start or (resolved_period_end - timedelta(days=default_span_days))
    if resolved_period_start > resolved_period_end:
        raise ValueError("period_start cannot be later than period_end.")
    return resolved_period_start, resolved_period_end


def _require_portfolio(session: Session, portfolio_id: int) -> None:
    if PortfolioRepository(session).get_by_id(portfolio_id) is None:
        raise PortfolioNotFoundError(f"Portfolio {portfolio_id} was not found.")


def _resolve_policy_targets(
    session: Session,
    target_specs: list[str],
) -> tuple[PortfolioPolicyTargetCreate, ...]:
    normalized_codes: set[str] = set()
    resolved_targets: list[PortfolioPolicyTargetCreate] = []
    fund_repo = FundMasterRepository(session)

    for spec in target_specs:
        parsed = _parse_policy_target_spec(spec)
        fund_code = parsed.fund_code.strip()
        if not fund_code:
            raise CommandError("fund_code cannot be blank.")
        if fund_code in normalized_codes:
            raise CommandError(f"Duplicate fund_code '{fund_code}' in policy targets.")
        normalized_codes.add(fund_code)
        _validate_policy_target_spec(parsed)

        fund = fund_repo.get_by_code(fund_code)
        if fund is None:
            raise CommandError(f"Fund '{fund_code}' was not found.")

        resolved_targets.append(
            PortfolioPolicyTargetCreate(
                fund_id=fund.id,
                target_weight_ratio=parsed.target_weight_ratio,
                min_weight_ratio=parsed.min_weight_ratio,
                max_weight_ratio=parsed.max_weight_ratio,
                add_allowed=parsed.add_allowed,
                trim_allowed=parsed.trim_allowed,
            )
        )

    return tuple(resolved_targets)


def _parse_policy_target_spec(spec: str) -> PolicyTargetSpec:
    allowed_keys = {
        "fund_code",
        "target_weight_ratio",
        "min_weight_ratio",
        "max_weight_ratio",
        "add_allowed",
        "trim_allowed",
    }
    raw_values: dict[str, str] = {}
    for item in spec.split(","):
        key, separator, value = item.partition("=")
        if separator == "":
            raise CommandError(
                "Invalid --target format. Expected comma-separated key=value pairs."
            )
        normalized_key = key.strip()
        if normalized_key not in allowed_keys:
            raise CommandError(f"Unsupported target key '{normalized_key}'.")
        raw_values[normalized_key] = value.strip()

    if "fund_code" not in raw_values:
        raise CommandError("Each --target must include fund_code.")
    if "target_weight_ratio" not in raw_values:
        raise CommandError("Each --target must include target_weight_ratio.")

    try:
        return PolicyTargetSpec(
            fund_code=raw_values["fund_code"],
            target_weight_ratio=_parse_decimal(raw_values["target_weight_ratio"]),
            min_weight_ratio=_parse_optional_decimal(raw_values.get("min_weight_ratio")),
            max_weight_ratio=_parse_optional_decimal(raw_values.get("max_weight_ratio")),
            add_allowed=_parse_optional_bool(raw_values.get("add_allowed"), default=True),
            trim_allowed=_parse_optional_bool(raw_values.get("trim_allowed"), default=True),
        )
    except InvalidOperation as exc:
        raise CommandError(f"Invalid decimal value in --target: {spec}") from exc


def _validate_policy_target_spec(target: PolicyTargetSpec) -> None:
    if (
        target.min_weight_ratio is not None
        and target.max_weight_ratio is not None
        and target.min_weight_ratio > target.max_weight_ratio
    ):
        raise CommandError(
            f"Target range for fund '{target.fund_code}' is invalid: "
            "min_weight_ratio cannot exceed max_weight_ratio."
        )
    if (
        target.min_weight_ratio is not None
        and target.min_weight_ratio > target.target_weight_ratio
    ):
        raise CommandError(
            f"Target range for fund '{target.fund_code}' is invalid: "
            "min_weight_ratio cannot exceed target_weight_ratio."
        )
    if (
        target.max_weight_ratio is not None
        and target.max_weight_ratio < target.target_weight_ratio
    ):
        raise CommandError(
            f"Target range for fund '{target.fund_code}' is invalid: "
            "max_weight_ratio cannot be below target_weight_ratio."
        )


def _parse_optional_decimal(raw_value: str | None) -> Decimal | None:
    if raw_value is None or raw_value == "":
        return None
    return _parse_decimal(raw_value)


def _parse_optional_bool(raw_value: str | None, *, default: bool) -> bool:
    if raw_value is None or raw_value == "":
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise CommandError(f"Invalid boolean value '{raw_value}'.")


def _build_decision_run_summary_payload(decision_run: DecisionRun) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        serialize_for_json(
            {
                "id": decision_run.id,
                "portfolio_id": decision_run.portfolio_id,
                "portfolio_code": decision_run.portfolio.portfolio_code,
                "portfolio_name": decision_run.portfolio.portfolio_name,
                "policy_id": decision_run.policy_id,
                "policy_name": decision_run.policy.policy_name if decision_run.policy is not None else None,
                "run_id": decision_run.run_id,
                "workflow_name": decision_run.workflow_name,
                "decision_date": decision_run.decision_date,
                "trigger_source": decision_run.trigger_source,
                "summary": decision_run.summary,
                "final_decision": decision_run.final_decision,
                "confidence_score": (
                    float(decision_run.confidence_score)
                    if decision_run.confidence_score is not None
                    else None
                ),
                "action_count": _count_actions(decision_run.actions_json),
                "created_by_agent": decision_run.created_by_agent,
                "created_at": decision_run.created_at,
            }
        ),
    )


def _build_decision_run_detail_payload(decision_run: DecisionRun) -> dict[str, Any]:
    payload = _build_decision_run_summary_payload(decision_run)
    payload["actions_json"] = serialize_for_json(decision_run.actions_json)
    payload["decision_summary_json"] = serialize_for_json(decision_run.decision_summary_json)
    return payload


def _count_actions(actions_json: list[dict[str, Any]] | dict[str, Any] | None) -> int:
    if isinstance(actions_json, list):
        return len(actions_json)
    if isinstance(actions_json, dict):
        return 1
    return 0


def _emit_json(payload: Any) -> None:
    print(json.dumps(serialize_for_json(payload), indent=2, sort_keys=True), file=sys.stdout)


def _emit_error(error: Exception) -> None:
    payload = {
        "error": str(error),
        "error_type": type(error).__name__,
    }
    print(json.dumps(serialize_for_json(payload), indent=2, sort_keys=True), file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = cast(CommandHandler, args.handler)
    session_factory = get_session_factory()

    with session_factory() as session:
        try:
            payload = handler(args, session)
        except (
            CommandError,
            DecisionFeedbackError,
            IncompletePortfolioSnapshotError,
            PortfolioNotFoundError,
            ValueError,
        ) as exc:
            session.rollback()
            _emit_error(exc)
            sys.exit(1)

    _emit_json(payload)


__all__ = ["main"]
