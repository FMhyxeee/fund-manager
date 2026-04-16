"""Unit tests for the manual strategy agent runtime."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fund_manager.agents.runtime import ManualStrategyAgent
from fund_manager.core.fact_packs import ReviewPositionFact, StrategyDebateFacts


def test_manual_strategy_agent_returns_evidence_backed_actions() -> None:
    agent = ManualStrategyAgent()

    result = agent.propose(build_facts())

    assert result.summary
    assert result.thesis
    assert result.confidence_level == "medium"
    assert len(result.evidence) >= 5
    assert result.proposed_actions
    assert result.proposed_actions[0].priority == "high"
    assert "manual concentration review" in result.proposed_actions[0].action.lower()
    assert result.proposed_actions[0].evidence_refs
    assert any("Top position weight:" in evidence for evidence in result.evidence)


def test_strategy_agent_drops_confidence_when_nav_is_missing() -> None:
    agent = ManualStrategyAgent()

    facts = build_facts(missing_nav_fund_codes=("000099",))
    result = agent.propose(facts)

    assert result.confidence_level == "low"
    assert any("missing" in evidence.lower() for evidence in result.evidence)
    assert result.proposed_actions
    assert "refresh" in result.proposed_actions[0].action.lower()


def test_strategy_agent_defers_when_valuation_points_are_sparse() -> None:
    agent = ManualStrategyAgent()

    facts = build_facts(valuation_point_count=1)
    result = agent.propose(facts)

    assert result.confidence_level == "low"


def test_strategy_agent_signals_caution_on_negative_return() -> None:
    agent = ManualStrategyAgent()

    facts = build_facts(period_return_ratio=Decimal("-0.052000"))
    result = agent.propose(facts)

    assert "caution" in result.summary.lower() or "risk" in result.summary.lower()
    assert any("negative" in risk.lower() for risk in result.risks)


def test_strategy_agent_flags_drawdown_risk() -> None:
    agent = ManualStrategyAgent()

    facts = build_facts(max_drawdown_ratio=Decimal("-0.087000"))
    result = agent.propose(facts)

    assert any("drawdown" in risk.lower() for risk in result.risks)


def test_strategy_agent_defaults_to_monitor_when_no_flags() -> None:
    agent = ManualStrategyAgent()

    facts = build_facts(
        period_return_ratio=Decimal("0.010000"),
        top_weight_positions=(
            ReviewPositionFact(
                fund_code="000001",
                fund_name="Balanced Fund",
                units=Decimal("10.000000"),
                current_value_amount=Decimal("10.2000"),
                weight_ratio=Decimal("0.300000"),
                unrealized_pnl_amount=Decimal("0.2000"),
                missing_nav=False,
            ),
        ),
    )
    result = agent.propose(facts)

    # When no risk flags are triggered, the agent should suggest a low-urgency action
    assert len(result.proposed_actions) >= 1
    assert result.proposed_actions[0].priority in ("low", "medium")


def test_strategy_agent_includes_period_window_in_evidence() -> None:
    agent = ManualStrategyAgent()

    facts = build_facts(
        period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 28),
    )
    result = agent.propose(facts)

    assert any("2026-02-01" in evidence for evidence in result.evidence)
    assert any("2026-02-28" in evidence for evidence in result.evidence)


def build_facts(
    *,
    period_start: date = date(2026, 3, 8),
    period_end: date = date(2026, 3, 15),
    period_return_ratio: Decimal = Decimal("0.139456"),
    valuation_point_count: int = 4,
    missing_nav_fund_codes: tuple[str, ...] = (),
    max_drawdown_ratio: Decimal = Decimal("-0.020000"),
    top_weight_positions: tuple[ReviewPositionFact, ...] | None = None,
) -> StrategyDebateFacts:
    return StrategyDebateFacts(
        portfolio_id=1,
        portfolio_code="main",
        portfolio_name="Main",
        base_currency_code="CNY",
        period_start=period_start,
        period_end=period_end,
        latest_valuation_date=date(2026, 3, 14),
        valuation_point_count=valuation_point_count,
        position_count=2,
        total_cost_amount=Decimal("27.0000"),
        total_market_value_amount=Decimal("33.5000"),
        unrealized_pnl_amount=Decimal("6.5000"),
        period_return_ratio=period_return_ratio,
        weekly_return_ratio=Decimal("0.139456"),
        monthly_return_ratio=Decimal("0.340000"),
        max_drawdown_ratio=max_drawdown_ratio,
        missing_nav_fund_codes=missing_nav_fund_codes,
        top_weight_positions=top_weight_positions
        if top_weight_positions is not None
        else (
            ReviewPositionFact(
                fund_code="000001",
                fund_name="Alpha Fund",
                units=Decimal("12.000000"),
                current_value_amount=Decimal("18.0000"),
                weight_ratio=Decimal("0.537313"),
                unrealized_pnl_amount=Decimal("6.0000"),
                missing_nav=False,
            ),
            ReviewPositionFact(
                fund_code="000002",
                fund_name="Beta Fund",
                units=Decimal("5.000000"),
                current_value_amount=Decimal("15.5000"),
                weight_ratio=Decimal("0.462687"),
                unrealized_pnl_amount=Decimal("0.5000"),
                missing_nav=False,
            ),
        ),
        top_gainers=(
            ReviewPositionFact(
                fund_code="000001",
                fund_name="Alpha Fund",
                units=Decimal("12.000000"),
                current_value_amount=Decimal("18.0000"),
                weight_ratio=Decimal("0.537313"),
                unrealized_pnl_amount=Decimal("6.0000"),
                missing_nav=False,
            ),
        ),
        top_laggards=(
            ReviewPositionFact(
                fund_code="000002",
                fund_name="Beta Fund",
                units=Decimal("5.000000"),
                current_value_amount=Decimal("15.5000"),
                weight_ratio=Decimal("0.462687"),
                unrealized_pnl_amount=Decimal("0.5000"),
                missing_nav=False,
            ),
        ),
        accounting_assumptions_note="Deterministic metrics only.",
    )
