"""Deterministic portfolio decision service backed by policy + canonical facts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from fund_manager.core.domain.decimal_constants import ZERO
from fund_manager.core.domain.metrics import quantize_money, quantize_ratio
from fund_manager.core.serialization import serialize_for_json
from fund_manager.core.services.policy_service import PolicyService, PortfolioPolicyDTO
from fund_manager.core.services.portfolio_service import PortfolioPositionDTO, PortfolioService

DECISION_ENGINE_NAME = "DecisionService"
DECISION_CONFIDENCE_NO_POLICY = Decimal("0.2000")
DECISION_CONFIDENCE_DEFER = Decimal("0.3000")
DECISION_CONFIDENCE_REBALANCE = Decimal("0.7000")
DECISION_CONFIDENCE_MONITOR = Decimal("0.8500")
HIGH_PRIORITY = "high"
MEDIUM_PRIORITY = "medium"
LOW_PRIORITY = "low"


@dataclass(frozen=True)
class DecisionActionDTO:
    """One deterministic action derived from policy and canonical facts."""

    action_type: str
    priority: str
    rationale: str
    requires_human_review: bool
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    fund_id: int | None = None
    fund_code: str | None = None
    fund_name: str | None = None
    current_weight_ratio: Decimal | None = None
    target_weight_ratio: Decimal | None = None
    min_weight_ratio: Decimal | None = None
    max_weight_ratio: Decimal | None = None
    delta_weight_ratio: Decimal | None = None
    suggested_amount: Decimal | None = None


@dataclass(frozen=True)
class PortfolioDecisionDTO:
    """Structured output for one deterministic daily decision run."""

    portfolio_id: int
    portfolio_code: str
    portfolio_name: str
    as_of_date: date
    policy_id: int | None
    policy_name: str | None
    final_decision: str
    summary: str
    confidence_score: Decimal
    missing_nav_fund_codes: tuple[str, ...]
    action_count: int
    total_market_value_amount: Decimal | None
    actions: tuple[DecisionActionDTO, ...]

    def to_dict(self) -> dict[str, object]:
        return serialize_for_json(asdict(self))


class DecisionService:
    """Convert canonical portfolio state + active policy into deterministic actions."""

    def __init__(
        self,
        session: Session,
        *,
        portfolio_service: PortfolioService | None = None,
        policy_service: PolicyService | None = None,
    ) -> None:
        self._portfolio_service = portfolio_service or PortfolioService(session)
        self._policy_service = policy_service or PolicyService(session)

    def evaluate_portfolio_decision(
        self,
        portfolio_id: int,
        *,
        as_of_date: date,
    ) -> PortfolioDecisionDTO:
        """Evaluate one portfolio against the active policy and return deterministic actions."""
        snapshot = self._portfolio_service.get_portfolio_snapshot(
            portfolio_id,
            as_of_date=as_of_date,
            workflow_name="daily_decision",
        )
        policy = self._policy_service.get_active_policy(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
        )

        if policy is None:
            actions = (
                DecisionActionDTO(
                    action_type="set_policy",
                    priority=HIGH_PRIORITY,
                    rationale=(
                        "No effective portfolio policy is active for this date, so the system "
                        "cannot produce deterministic rebalance instructions."
                    ),
                    requires_human_review=True,
                    reason_codes=("no_active_policy",),
                    evidence_refs=(),
                ),
            )
            return PortfolioDecisionDTO(
                portfolio_id=snapshot.portfolio_id,
                portfolio_code=snapshot.portfolio_code,
                portfolio_name=snapshot.portfolio_name,
                as_of_date=as_of_date,
                policy_id=None,
                policy_name=None,
                final_decision="no_active_policy",
                summary="No active portfolio policy was found for this decision date.",
                confidence_score=DECISION_CONFIDENCE_NO_POLICY,
                missing_nav_fund_codes=(),
                action_count=len(actions),
                total_market_value_amount=snapshot.total_market_value_amount,
                actions=actions,
            )

        if snapshot.missing_nav_fund_codes:
            actions = tuple(
                DecisionActionDTO(
                    action_type="refresh_data",
                    priority=HIGH_PRIORITY,
                    rationale=(
                        "Canonical valuation is incomplete, so policy actions should be deferred "
                        "until authoritative NAV coverage is restored."
                    ),
                    requires_human_review=False,
                    reason_codes=("missing_nav",),
                    evidence_refs=(f"Missing NAV coverage: {fund_code}.",),
                    fund_code=fund_code,
                )
                for fund_code in snapshot.missing_nav_fund_codes
            )
            return PortfolioDecisionDTO(
                portfolio_id=snapshot.portfolio_id,
                portfolio_code=snapshot.portfolio_code,
                portfolio_name=snapshot.portfolio_name,
                as_of_date=as_of_date,
                policy_id=policy.policy_id,
                policy_name=policy.policy_name,
                final_decision="defer_until_complete_data",
                summary=(
                    "Decision run deferred because one or more held funds still lack current "
                    "authoritative NAV coverage."
                ),
                confidence_score=DECISION_CONFIDENCE_DEFER,
                missing_nav_fund_codes=snapshot.missing_nav_fund_codes,
                action_count=len(actions),
                total_market_value_amount=snapshot.total_market_value_amount,
                actions=actions,
            )

        actions = self._build_policy_actions(snapshot.positions, policy, snapshot.total_market_value_amount)
        if actions:
            final_decision = "rebalance_required"
            summary = (
                f"Detected {len(actions)} deterministic policy action(s) for policy "
                f"{policy.policy_name}."
            )
            confidence_score = DECISION_CONFIDENCE_REBALANCE
        else:
            final_decision = "monitor"
            summary = f"Current holdings remain within the active policy bands for {policy.policy_name}."
            confidence_score = DECISION_CONFIDENCE_MONITOR

        return PortfolioDecisionDTO(
            portfolio_id=snapshot.portfolio_id,
            portfolio_code=snapshot.portfolio_code,
            portfolio_name=snapshot.portfolio_name,
            as_of_date=as_of_date,
            policy_id=policy.policy_id,
            policy_name=policy.policy_name,
            final_decision=final_decision,
            summary=summary,
            confidence_score=confidence_score,
            missing_nav_fund_codes=(),
            action_count=len(actions),
            total_market_value_amount=snapshot.total_market_value_amount,
            actions=actions,
        )

    def _build_policy_actions(
        self,
        positions: tuple[PortfolioPositionDTO, ...],
        policy: PortfolioPolicyDTO,
        total_market_value_amount: Decimal | None,
    ) -> tuple[DecisionActionDTO, ...]:
        positions_by_fund_id = {position.fund_id: position for position in positions}
        covered_fund_ids: set[int] = set()
        actions: list[DecisionActionDTO] = []

        for target in policy.targets:
            covered_fund_ids.add(target.fund_id)
            current_position = positions_by_fund_id.get(target.fund_id)
            current_weight = (
                current_position.weight_ratio
                if current_position is not None and current_position.weight_ratio is not None
                else ZERO
            )
            min_weight = (
                target.min_weight_ratio
                if target.min_weight_ratio is not None
                else quantize_ratio(max(ZERO, target.target_weight_ratio - policy.rebalance_threshold_ratio))
            )
            max_weight = (
                target.max_weight_ratio
                if target.max_weight_ratio is not None
                else quantize_ratio(target.target_weight_ratio + policy.rebalance_threshold_ratio)
            )

            if current_weight < min_weight and target.add_allowed:
                delta_weight = quantize_ratio(target.target_weight_ratio - current_weight)
                suggested_amount = self._maybe_amount(total_market_value_amount, delta_weight)
                actions.append(
                    DecisionActionDTO(
                        action_type="add",
                        priority=self._priority_for_delta(delta_weight),
                        rationale=(
                            "Current weight is below the policy band, so the portfolio should "
                            "consider adding exposure back toward the target weight."
                        ),
                        requires_human_review=True,
                        reason_codes=("below_target_band",),
                        evidence_refs=(
                            f"Current weight {self._format_ratio(current_weight)} is below policy minimum "
                            f"{self._format_ratio(min_weight)}.",
                        ),
                        fund_id=target.fund_id,
                        fund_code=target.fund_code,
                        fund_name=target.fund_name,
                        current_weight_ratio=current_weight,
                        target_weight_ratio=target.target_weight_ratio,
                        min_weight_ratio=min_weight,
                        max_weight_ratio=max_weight,
                        delta_weight_ratio=delta_weight,
                        suggested_amount=suggested_amount,
                    )
                )
                continue

            if current_weight > max_weight and target.trim_allowed:
                delta_weight = quantize_ratio(current_weight - target.target_weight_ratio)
                suggested_amount = self._maybe_amount(total_market_value_amount, delta_weight)
                actions.append(
                    DecisionActionDTO(
                        action_type="trim",
                        priority=self._priority_for_delta(delta_weight),
                        rationale=(
                            "Current weight is above the policy band, so the portfolio should "
                            "consider trimming exposure back toward the target weight."
                        ),
                        requires_human_review=True,
                        reason_codes=("above_target_band",),
                        evidence_refs=(
                            f"Current weight {self._format_ratio(current_weight)} is above policy maximum "
                            f"{self._format_ratio(max_weight)}.",
                        ),
                        fund_id=target.fund_id,
                        fund_code=target.fund_code,
                        fund_name=target.fund_name,
                        current_weight_ratio=current_weight,
                        target_weight_ratio=target.target_weight_ratio,
                        min_weight_ratio=min_weight,
                        max_weight_ratio=max_weight,
                        delta_weight_ratio=delta_weight,
                        suggested_amount=suggested_amount,
                    )
                )

        if policy.max_single_position_weight_ratio is not None:
            for position in positions:
                if position.fund_id in covered_fund_ids:
                    continue
                if position.weight_ratio is None:
                    continue
                if position.weight_ratio <= policy.max_single_position_weight_ratio:
                    continue
                delta_weight = quantize_ratio(
                    position.weight_ratio - policy.max_single_position_weight_ratio
                )
                actions.append(
                    DecisionActionDTO(
                        action_type="trim",
                        priority=self._priority_for_delta(delta_weight),
                        rationale=(
                            "This holding is outside the named policy targets and also exceeds the "
                            "portfolio-wide single-position cap."
                        ),
                        requires_human_review=True,
                        reason_codes=("above_portfolio_cap", "missing_policy_target"),
                        evidence_refs=(
                            f"Current weight {self._format_ratio(position.weight_ratio)} exceeds cap "
                            f"{self._format_ratio(policy.max_single_position_weight_ratio)}.",
                        ),
                        fund_id=position.fund_id,
                        fund_code=position.fund_code,
                        fund_name=position.fund_name,
                        current_weight_ratio=position.weight_ratio,
                        target_weight_ratio=policy.max_single_position_weight_ratio,
                        delta_weight_ratio=delta_weight,
                        suggested_amount=self._maybe_amount(total_market_value_amount, delta_weight),
                    )
                )

        return tuple(sorted(actions, key=self._action_sort_key))

    def _maybe_amount(
        self,
        total_market_value_amount: Decimal | None,
        delta_weight_ratio: Decimal,
    ) -> Decimal | None:
        if total_market_value_amount is None or total_market_value_amount <= ZERO:
            return None
        if delta_weight_ratio <= ZERO:
            return None
        return quantize_money(total_market_value_amount * delta_weight_ratio)

    def _priority_for_delta(self, delta_weight_ratio: Decimal) -> str:
        if delta_weight_ratio >= Decimal("0.100000"):
            return HIGH_PRIORITY
        if delta_weight_ratio >= Decimal("0.050000"):
            return MEDIUM_PRIORITY
        return LOW_PRIORITY

    def _action_sort_key(self, action: DecisionActionDTO) -> tuple[int, str, str]:
        priority_rank = {HIGH_PRIORITY: 0, MEDIUM_PRIORITY: 1, LOW_PRIORITY: 2}
        return (
            priority_rank.get(action.priority, 99),
            action.action_type,
            action.fund_code or "",
        )

    def _format_ratio(self, value: Decimal) -> str:
        return f"{(value * Decimal('100')).quantize(Decimal('0.01'))}%"


__all__ = [
    "DECISION_ENGINE_NAME",
    "DecisionActionDTO",
    "DecisionService",
    "PortfolioDecisionDTO",
]
