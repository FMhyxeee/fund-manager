"""Unit tests for the manual judge agent runtime."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fund_manager.agents.runtime import ManualJudgeAgent
from fund_manager.core.ai_artifacts import (
    ChallengerOutput,
    JudgeOutput,
    StrategyAction,
    StrategyProposalOutput,
)
from fund_manager.core.fact_packs import ReviewPositionFact, StrategyDebateFacts


def test_manual_judge_agent_synthesizes_final_recommendation() -> None:
    agent = ManualJudgeAgent()

    result = agent.judge(
        build_facts(),
        build_strategy_output(),
        build_challenger_output(),
    )

    assert isinstance(result, JudgeOutput)
    assert result.summary
    assert result.thesis
    assert result.final_judgment == "monitor_with_concentration_review"
    assert result.confidence_level == "medium"
    assert result.confidence_score == Decimal("0.6500")
    assert result.proposed_actions
    assert result.counterarguments


def build_facts() -> StrategyDebateFacts:
    return StrategyDebateFacts(
        portfolio_id=1,
        portfolio_code="main",
        portfolio_name="Main",
        base_currency_code="CNY",
        period_start=date(2026, 3, 8),
        period_end=date(2026, 3, 15),
        latest_valuation_date=date(2026, 3, 14),
        valuation_point_count=4,
        position_count=2,
        total_cost_amount=Decimal("27.0000"),
        total_market_value_amount=Decimal("33.5000"),
        unrealized_pnl_amount=Decimal("6.5000"),
        period_return_ratio=Decimal("0.139456"),
        weekly_return_ratio=Decimal("0.139456"),
        monthly_return_ratio=Decimal("0.340000"),
        max_drawdown_ratio=Decimal("-0.020000"),
        missing_nav_fund_codes=(),
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
        top_gainers=(),
        top_laggards=(),
        accounting_assumptions_note="Deterministic metrics only.",
    )


def build_strategy_output() -> StrategyProposalOutput:
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
                action=(
                    "Prepare a manual concentration review for Alpha Fund before adding "
                    "further exposure."
                ),
                rationale="Alpha Fund remains above the concentration watch line.",
                evidence_refs=("Top position weight: Alpha Fund at +53.73%.",),
                priority="high",
            ),
        ),
        risks=("Alpha Fund remains above the concentration watch line.",),
        confidence_level="medium",
    )


def build_challenger_output() -> ChallengerOutput:
    return ChallengerOutput(
        summary="The proposal identifies the main issue but still needs lower certainty.",
        critique_points=(
            "The stated confidence may be too strong relative to the limited evidence and "
            "should be defended more carefully.",
        ),
        evidence_gaps=(
            "The current evidence does not include target allocation bands or a formal "
            "rebalance threshold.",
        ),
        counterarguments=(
            "Maintaining a pure monitoring stance could be more defensible until another "
            "full review window confirms the trend.",
        ),
        confidence_level="medium",
    )
