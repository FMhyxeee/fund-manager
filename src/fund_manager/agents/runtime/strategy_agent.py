"""Manual StrategyAgent implementation."""

from __future__ import annotations

from decimal import Decimal

from fund_manager.agents.runtime.shared import (
    PromptDefinition,
    format_money,
    format_ratio_as_percent,
    load_prompt_definition,
)
from fund_manager.core.ai_artifacts import StrategyAction, StrategyProposalOutput
from fund_manager.core.fact_packs import StrategyDebateFacts

HIGH_CONCENTRATION_RATIO = Decimal("0.400000")
NEGATIVE_RETURN_RATIO = Decimal("0")
LOW_CONFIDENCE = "low"
MEDIUM_CONFIDENCE = "medium"
class ManualStrategyAgent:
    """Deterministic placeholder StrategyAgent for the debate workflow."""

    def __init__(
        self,
        *,
        prompt_name: str = "strategy_agent.md",
    ) -> None:
        # Placeholder manual runtime until a debate-capable strategy agent is wired in.
        self._prompt = load_prompt_definition(prompt_name)

    @property
    def agent_name(self) -> str:
        return "StrategyAgent"

    @property
    def model_name(self) -> str:
        return "manual-strategy-agent-v1"

    @property
    def prompt(self) -> PromptDefinition:
        return self._prompt

    def propose(self, facts: StrategyDebateFacts) -> StrategyProposalOutput:
        """Turn structured facts into a first-pass strategy proposal."""
        evidence = tuple(self._build_evidence(facts))
        risks = tuple(self._build_risks(facts))
        proposed_actions = tuple(self._build_actions(facts, evidence))
        return StrategyProposalOutput(
            summary=self._build_summary(facts),
            thesis=self._build_thesis(facts),
            evidence=evidence,
            proposed_actions=proposed_actions,
            risks=risks,
            confidence_level=self._build_confidence_level(facts),
        )

    def _build_summary(self, facts: StrategyDebateFacts) -> str:
        if facts.missing_nav_fund_codes:
            missing_funds = ", ".join(facts.missing_nav_fund_codes)
            return (
                "The evidence base is incomplete, so strategy action should stay conservative "
                f"until authoritative NAV coverage is refreshed for {missing_funds}."
            )
        if facts.period_return_ratio is None:
            return (
                "The portfolio can be monitored, but the current review window still lacks "
                "enough valuation history for a stronger strategy call."
            )
        if facts.period_return_ratio > NEGATIVE_RETURN_RATIO:
            return (
                "The recent valuation path is constructive, but concentration and downside "
                "control still matter more than chasing a single positive window."
            )
        return (
            "The latest evidence argues for caution: recent returns are weak enough that the "
            "next action should prioritize risk review over adding conviction."
        )

    def _build_thesis(self, facts: StrategyDebateFacts) -> str:
        if facts.missing_nav_fund_codes:
            return (
                "Defer any stronger allocation change and refresh missing valuation evidence "
                "before making a new strategy call."
            )

        largest_position = facts.top_weight_positions[0] if facts.top_weight_positions else None
        if (
            largest_position is not None
            and largest_position.weight_ratio is not None
            and largest_position.weight_ratio >= HIGH_CONCENTRATION_RATIO
        ):
            return (
                "Keep the portfolio broadly in place for now, but prioritize a manual review of "
                "the largest position before adding more concentration."
            )

        if (
            facts.period_return_ratio is not None
            and facts.period_return_ratio < NEGATIVE_RETURN_RATIO
        ):
            return (
                "Prefer a monitor-and-review stance until the portfolio shows a steadier recovery "
                "across another complete evidence window."
            )

        return (
            "Maintain the current allocation stance while monitoring whether recent performance "
            "and concentration remain within the intended risk posture."
        )

    def _build_evidence(self, facts: StrategyDebateFacts) -> list[str]:
        evidence = [
            f"Review window: {facts.period_start.isoformat()} to {facts.period_end.isoformat()}.",
            f"Tracked positions: {facts.position_count}.",
            f"Valuation coverage: {facts.valuation_point_count} point(s).",
            (
                "Total cost basis: "
                f"{format_money(facts.total_cost_amount)} {facts.base_currency_code}."
            ),
        ]
        if facts.total_market_value_amount is not None:
            evidence.append(
                "Total market value: "
                f"{format_money(facts.total_market_value_amount)} {facts.base_currency_code}."
            )
        if facts.period_return_ratio is not None:
            evidence.append(
                f"Requested-period return: {format_ratio_as_percent(facts.period_return_ratio)}."
            )
        if facts.monthly_return_ratio is not None:
            evidence.append(
                f"Trailing 30-day return: {format_ratio_as_percent(facts.monthly_return_ratio)}."
            )
        if facts.max_drawdown_ratio is not None:
            evidence.append(
                f"Period max drawdown: {format_ratio_as_percent(facts.max_drawdown_ratio)}."
            )
        if facts.top_weight_positions:
            largest_position = facts.top_weight_positions[0]
            if largest_position.weight_ratio is not None:
                evidence.append(
                    f"Top position weight: {largest_position.fund_name} at "
                    f"{format_ratio_as_percent(largest_position.weight_ratio)}."
                )
        if facts.top_laggards:
            laggard = facts.top_laggards[0]
            if laggard.unrealized_pnl_amount is not None:
                evidence.append(
                    f"Weakest unrealized contribution: {laggard.fund_name} at "
                    f"{format_money(laggard.unrealized_pnl_amount)} {facts.base_currency_code}."
                )
        if facts.missing_nav_fund_codes:
            evidence.append(
                "Missing NAV coverage: " + ", ".join(facts.missing_nav_fund_codes) + "."
            )
        return evidence

    def _build_actions(
        self,
        facts: StrategyDebateFacts,
        evidence: tuple[str, ...],
    ) -> list[StrategyAction]:
        actions: list[StrategyAction] = []
        evidence_map = set(evidence)

        if facts.missing_nav_fund_codes:
            missing_nav_ref = (
                "Missing NAV coverage: " + ", ".join(facts.missing_nav_fund_codes) + "."
            )
            actions.append(
                StrategyAction(
                    action="Refresh missing NAV data before taking a stronger allocation stance.",
                    rationale=(
                        "Canonical valuation is incomplete, so any stronger recommendation would "
                        "overstate certainty."
                    ),
                    evidence_refs=(missing_nav_ref,) if missing_nav_ref in evidence_map else (),
                    priority="high",
                )
            )
            return actions

        if facts.top_weight_positions:
            largest_position = facts.top_weight_positions[0]
            if (
                largest_position.weight_ratio is not None
                and largest_position.weight_ratio >= HIGH_CONCENTRATION_RATIO
            ):
                actions.append(
                    StrategyAction(
                        action=(
                            f"Prepare a manual concentration review for "
                            f"{largest_position.fund_name} "
                            "before adding further exposure."
                        ),
                        rationale=(
                            "The largest holding already sits above the watch line, so additional "
                            "risk should be reviewed before it compounds."
                        ),
                        evidence_refs=(
                            f"Top position weight: {largest_position.fund_name} at "
                            f"{format_ratio_as_percent(largest_position.weight_ratio)}.",
                        ),
                        priority="high",
                    )
                )

        if facts.top_laggards:
            laggard = facts.top_laggards[0]
            if laggard.unrealized_pnl_amount is not None:
                actions.append(
                    StrategyAction(
                        action=(
                            f"Keep {laggard.fund_name} on the watch list until another review "
                            "window confirms whether weakness is persistent."
                        ),
                        rationale=(
                            "One weak contributor is visible in the current fact set, but a single "
                            "window is not enough to justify a stronger conclusion."
                        ),
                        evidence_refs=(
                            f"Weakest unrealized contribution: {laggard.fund_name} at "
                            f"{format_money(laggard.unrealized_pnl_amount)} "
                            f"{facts.base_currency_code}.",
                        ),
                        priority="medium",
                    )
                )

        if not actions:
            actions.append(
                StrategyAction(
                    action="Keep the current allocation under observation and revisit next cycle.",
                    rationale=(
                        "The current evidence does not justify a stronger intervention beyond "
                        "continued monitoring."
                    ),
                    evidence_refs=(
                        "Requested-period return: "
                        f"{format_ratio_as_percent(facts.period_return_ratio)}.",
                    )
                    if facts.period_return_ratio is not None
                    else (),
                    priority="medium",
                )
            )
        return actions

    def _build_risks(self, facts: StrategyDebateFacts) -> list[str]:
        risks: list[str] = []
        if facts.missing_nav_fund_codes:
            risks.append(
                "The strategy evidence is incomplete because one or more funds still lack "
                "authoritative NAV data."
            )
        if facts.top_weight_positions:
            largest_position = facts.top_weight_positions[0]
            if (
                largest_position.weight_ratio is not None
                and largest_position.weight_ratio >= HIGH_CONCENTRATION_RATIO
            ):
                risks.append(
                    f"{largest_position.fund_name} remains above the concentration watch line."
                )
        if (
            facts.period_return_ratio is not None
            and facts.period_return_ratio < NEGATIVE_RETURN_RATIO
        ):
            risks.append("Recent requested-period performance is negative.")
        if (
            facts.max_drawdown_ratio is not None
            and facts.max_drawdown_ratio < NEGATIVE_RETURN_RATIO
        ):
            risks.append(
                "The review window includes a drawdown of "
                f"{format_ratio_as_percent(facts.max_drawdown_ratio)}."
            )
        if not risks:
            risks.append("No urgent strategy risk dominates the current deterministic fact set.")
        return risks

    def _build_confidence_level(self, facts: StrategyDebateFacts) -> str:
        if facts.missing_nav_fund_codes or facts.valuation_point_count < 2:
            return LOW_CONFIDENCE
        return MEDIUM_CONFIDENCE


__all__ = [
    "HIGH_CONCENTRATION_RATIO",
    "LOW_CONFIDENCE",
    "MEDIUM_CONFIDENCE",
    "ManualStrategyAgent",
]
