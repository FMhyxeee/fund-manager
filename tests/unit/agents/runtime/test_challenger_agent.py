"""Unit tests for the manual challenger agent runtime."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from fund_manager.agents.runtime import (
    ManualChallengerAgent,
    ReviewPositionFact,
    StrategyAction,
    StrategyDebateFacts,
    StrategyProposalOutput,
    validate_critiques_distinct_from_proposal,
)


def test_manual_challenger_agent_critiques_instead_of_restating() -> None:
    agent = ManualChallengerAgent()
    proposal = build_strategy_output()

    result = agent.challenge(build_facts(), proposal)

    assert result.summary
    assert result.critique_points
    assert result.evidence_gaps
    assert result.counterarguments
    proposal_text = proposal.thesis.lower()
    assert all(point.lower() != proposal_text for point in result.critique_points)
    assert all(
        proposal.proposed_actions[0].action.lower() not in point.lower()
        for point in result.critique_points
    )


def test_validate_critiques_distinct_from_proposal_rejects_restatement() -> None:
    proposal = build_strategy_output()

    with pytest.raises(ValueError, match="must not restate the proposal"):
        validate_critiques_distinct_from_proposal(
            proposal,
            (
                "Prepare a manual concentration review for Alpha Fund before adding further exposure.",
            ),
        )


def test_challenger_rejects_empty_critique_points() -> None:
    proposal = build_strategy_output()

    with pytest.raises(ValueError, match="at least one critique point"):
        validate_critiques_distinct_from_proposal(proposal, ())


def test_challenger_drops_confidence_when_nav_is_missing() -> None:
    agent = ManualChallengerAgent()

    facts = build_facts(missing_nav_fund_codes=("000099",))
    proposal = build_strategy_output()
    result = agent.challenge(facts, proposal)

    assert result.confidence_level == "low"
    assert any(
        "incomplete" in point.lower() or "incomplete" in result.summary.lower()
        for point in result.critique_points
    )


def test_challenger_flags_short_valuation_window() -> None:
    agent = ManualChallengerAgent()

    facts = build_facts(valuation_point_count=1)
    proposal = build_strategy_output()
    result = agent.challenge(facts, proposal)

    assert any("valuation" in point.lower() for point in result.critique_points)


def test_challenger_flags_overconfidence_in_proposal() -> None:
    agent = ManualChallengerAgent()

    facts = build_facts()
    proposal = build_strategy_output(confidence_level="medium")
    result = agent.challenge(facts, proposal)

    assert any("confidence" in point.lower() for point in result.critique_points)


def test_challenger_identifies_evidence_gaps() -> None:
    agent = ManualChallengerAgent()

    facts = build_facts(valuation_point_count=2)
    proposal = build_strategy_output()
    result = agent.challenge(facts, proposal)

    assert result.evidence_gaps
    assert any(
        "target allocation" in gap.lower() or "rebalance" in gap.lower()
        for gap in result.evidence_gaps
    )


def test_challenger_produces_counterarguments() -> None:
    agent = ManualChallengerAgent()

    facts = build_facts()
    proposal = build_strategy_output()
    result = agent.challenge(facts, proposal)

    assert result.counterarguments
    assert any(
        "concentration" in arg.lower() or "monitor" in arg.lower()
        for arg in result.counterarguments
    )


def build_facts(
    *,
    valuation_point_count: int = 4,
    missing_nav_fund_codes: tuple[str, ...] = (),
) -> StrategyDebateFacts:
    return StrategyDebateFacts(
        portfolio_id=1,
        portfolio_code="main",
        portfolio_name="Main",
        base_currency_code="CNY",
        period_start=date(2026, 3, 8),
        period_end=date(2026, 3, 15),
        latest_valuation_date=date(2026, 3, 14),
        valuation_point_count=valuation_point_count,
        position_count=2,
        total_cost_amount=Decimal("27.0000"),
        total_market_value_amount=Decimal("33.5000"),
        unrealized_pnl_amount=Decimal("6.5000"),
        period_return_ratio=Decimal("0.139456"),
        weekly_return_ratio=Decimal("0.139456"),
        monthly_return_ratio=Decimal("0.340000"),
        max_drawdown_ratio=Decimal("-0.020000"),
        missing_nav_fund_codes=missing_nav_fund_codes,
        top_weight_positions=(
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


def build_strategy_output(
    *,
    confidence_level: str = "medium",
) -> StrategyProposalOutput:
    return StrategyProposalOutput(
        summary="Positive week, but concentration still matters.",
        thesis=(
            "Keep the portfolio broadly in place for now, but prioritize a manual review of "
            "the largest position before adding more concentration."
        ),
        evidence=(
            "Requested-period return: +13.95%.",
            "Top position weight: Alpha Fund at +53.73%.",
        ),
        proposed_actions=(
            StrategyAction(
                action="Prepare a manual concentration review for Alpha Fund before adding further exposure.",
                rationale="Alpha Fund remains above the concentration watch line.",
                evidence_refs=("Top position weight: Alpha Fund at +53.73%.",),
                priority="high",
            ),
        ),
        risks=("Alpha Fund remains above the concentration watch line.",),
        confidence_level=confidence_level,
    )
