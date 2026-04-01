"""ReviewAgent runtime contracts and the first manual implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol

HIGH_CONCENTRATION_RATIO = Decimal("0.400000")
SEVERE_DRAWDOWN_RATIO = Decimal("-0.050000")


@dataclass(frozen=True)
class PromptDefinition:
    """Loaded prompt text plus its traceable file reference."""

    name: str
    path: Path
    content: str


@dataclass(frozen=True)
class ReviewPositionFact:
    """Bounded position-level facts prepared by the workflow coordinator."""

    fund_code: str
    fund_name: str
    units: Decimal
    current_value_amount: Decimal | None
    weight_ratio: Decimal | None
    unrealized_pnl_amount: Decimal | None
    missing_nav: bool


@dataclass(frozen=True)
class WeeklyReviewFacts:
    """Structured facts sent to ReviewAgent for one weekly review run."""

    portfolio_id: int
    portfolio_code: str
    portfolio_name: str
    base_currency_code: str
    period_start: date
    period_end: date
    latest_valuation_date: date | None
    valuation_point_count: int
    position_count: int
    total_cost_amount: Decimal
    total_market_value_amount: Decimal | None
    unrealized_pnl_amount: Decimal | None
    daily_return_ratio: Decimal | None
    period_return_ratio: Decimal | None
    monthly_return_ratio: Decimal | None
    max_drawdown_ratio: Decimal | None
    missing_nav_fund_codes: tuple[str, ...]
    top_weight_positions: tuple[ReviewPositionFact, ...]
    top_gainers: tuple[ReviewPositionFact, ...]
    top_laggards: tuple[ReviewPositionFact, ...]
    accounting_assumptions_note: str


@dataclass(frozen=True)
class ReviewAgentOutput:
    """Structured weekly review analysis produced by ReviewAgent."""

    summary: str
    fact_statements: tuple[str, ...]
    interpretation_notes: tuple[str, ...]
    key_drivers: tuple[str, ...]
    risks_and_concerns: tuple[str, ...]
    recommendation_notes: tuple[str, ...]
    open_questions: tuple[str, ...]


class ReviewAgent(Protocol):
    """Runtime contract for a bounded weekly review agent."""

    @property
    def agent_name(self) -> str:
        """Human-readable logical agent name."""

    @property
    def model_name(self) -> str | None:
        """Concrete runtime identifier when available."""

    @property
    def prompt(self) -> PromptDefinition:
        """Prompt definition used by the runtime."""

    def review(self, facts: WeeklyReviewFacts) -> ReviewAgentOutput:
        """Produce a structured weekly review from prepared facts only."""


class ManualReviewAgent:
    """Deterministic placeholder ReviewAgent for the first manual workflow."""

    def __init__(
        self,
        *,
        prompt_name: str = "review_agent.md",
    ) -> None:
        self._prompt = load_prompt_definition(prompt_name)

    @property
    def agent_name(self) -> str:
        return "ReviewAgent"

    @property
    def model_name(self) -> str:
        return "manual-review-agent-v1"

    @property
    def prompt(self) -> PromptDefinition:
        return self._prompt

    def review(self, facts: WeeklyReviewFacts) -> ReviewAgentOutput:
        """Turn structured facts into a first-pass weekly review summary."""
        fact_statements = self._build_fact_statements(facts)
        interpretation_notes = self._build_interpretation_notes(facts)
        key_drivers = self._build_key_drivers(facts)
        risks_and_concerns = self._build_risks_and_concerns(facts)
        recommendation_notes = self._build_recommendations(facts, risks_and_concerns)
        open_questions = self._build_open_questions(facts)

        return ReviewAgentOutput(
            summary=self._build_summary(facts),
            fact_statements=tuple(fact_statements),
            interpretation_notes=tuple(interpretation_notes),
            key_drivers=tuple(key_drivers),
            risks_and_concerns=tuple(risks_and_concerns),
            recommendation_notes=tuple(recommendation_notes),
            open_questions=tuple(open_questions),
        )

    def _build_summary(self, facts: WeeklyReviewFacts) -> str:
        if facts.missing_nav_fund_codes:
            missing_funds = ", ".join(facts.missing_nav_fund_codes)
            return (
                "Weekly review is partially complete because authoritative NAV data is still "
                f"missing for {missing_funds}."
            )

        if facts.period_return_ratio is None:
            return (
                "Weekly review captured the latest portfolio state, but the requested window "
                "does not yet have enough valuation points for a full period-return reading."
            )

        weekly_return_percent = format_ratio_as_percent(facts.period_return_ratio)
        if facts.period_return_ratio > Decimal("0"):
            return (
                f"{facts.portfolio_name} finished the review window higher, with a "
                f"{weekly_return_percent} period return across the available valuation history."
            )
        if facts.period_return_ratio < Decimal("0"):
            return (
                f"{facts.portfolio_name} finished the review window lower, with a "
                f"{weekly_return_percent} period return across the available valuation history."
            )
        return (
            f"{facts.portfolio_name} was effectively flat for the review window, with a "
            f"{weekly_return_percent} period return."
        )

    def _build_fact_statements(self, facts: WeeklyReviewFacts) -> list[str]:
        statements = [
            f"Review window: {facts.period_start.isoformat()} to {facts.period_end.isoformat()}.",
            (
                f"Valuation coverage: {facts.valuation_point_count} point(s)"
                + (
                    f", latest valuation on {facts.latest_valuation_date.isoformat()}."
                    if facts.latest_valuation_date is not None
                    else "."
                )
            ),
            f"Tracked positions: {facts.position_count}.",
            "Total cost basis: "
            f"{format_money(facts.total_cost_amount)} {facts.base_currency_code}.",
        ]
        if facts.total_market_value_amount is not None:
            statements.append(
                "Total market value: "
                f"{format_money(facts.total_market_value_amount)} {facts.base_currency_code}."
            )
        if facts.unrealized_pnl_amount is not None:
            statements.append(
                "Unrealized PnL: "
                f"{format_money(facts.unrealized_pnl_amount)} {facts.base_currency_code}."
            )
        if facts.period_return_ratio is not None:
            statements.append(
                f"Requested-period return: {format_ratio_as_percent(facts.period_return_ratio)}."
            )
        if facts.monthly_return_ratio is not None:
            statements.append(
                f"Trailing 30-day return: {format_ratio_as_percent(facts.monthly_return_ratio)}."
            )
        if facts.max_drawdown_ratio is not None:
            statements.append(
                f"Period max drawdown: {format_ratio_as_percent(facts.max_drawdown_ratio)}."
            )
        if facts.missing_nav_fund_codes:
            statements.append(
                "Missing NAV coverage: " + ", ".join(facts.missing_nav_fund_codes) + "."
            )
        return statements

    def _build_interpretation_notes(self, facts: WeeklyReviewFacts) -> list[str]:
        notes: list[str] = []
        if facts.period_return_ratio is None:
            notes.append(
                "The coordinator could not compute a full requested-period return because the "
                "window does not yet contain at least two valuation observations."
            )
        elif facts.period_return_ratio > Decimal("0"):
            notes.append(
                "The latest available valuation path indicates a positive weekly trend rather "
                "than a drawdown-led week."
            )
        elif facts.period_return_ratio < Decimal("0"):
            notes.append(
                "The latest available valuation path indicates the portfolio gave back value "
                "during the requested review window."
            )
        else:
            notes.append(
                "The latest available valuation path was flat, so the portfolio ended the week "
                "close to where it started."
            )

        if facts.top_weight_positions:
            largest_position = facts.top_weight_positions[0]
            if largest_position.weight_ratio is not None:
                notes.append(
                    f"{largest_position.fund_name} remained the largest position at "
                    f"{format_ratio_as_percent(largest_position.weight_ratio)} of measured value."
                )

        if facts.missing_nav_fund_codes:
            notes.append(
                "Because one or more funds still lack current NAV data, any market-value-based "
                "conclusions should be treated as incomplete until the next data refresh."
            )
        return notes

    def _build_key_drivers(self, facts: WeeklyReviewFacts) -> list[str]:
        drivers: list[str] = []
        if facts.top_weight_positions:
            top_weights = ", ".join(
                self._describe_position_weight(position)
                for position in facts.top_weight_positions
            )
            drivers.append(f"Top weight exposures: {top_weights}.")

        if facts.top_gainers:
            top_gainer = facts.top_gainers[0]
            if top_gainer.unrealized_pnl_amount is not None:
                drivers.append(
                    f"Largest unrealized gain sits in {top_gainer.fund_name} at "
                    f"{format_money(top_gainer.unrealized_pnl_amount)} "
                    f"{facts.base_currency_code}."
                )

        if facts.top_laggards:
            top_laggard = facts.top_laggards[0]
            if top_laggard.unrealized_pnl_amount is not None:
                drivers.append(
                    f"Weakest unrealized contribution comes from {top_laggard.fund_name} at "
                    f"{format_money(top_laggard.unrealized_pnl_amount)} "
                    f"{facts.base_currency_code}."
                )

        if not drivers:
            drivers.append(
                "No concentrated driver stood out yet because the available valuation coverage "
                "is still limited."
            )
        return drivers

    def _build_risks_and_concerns(self, facts: WeeklyReviewFacts) -> list[str]:
        risks: list[str] = []
        if facts.missing_nav_fund_codes:
            risks.append(
                "Authoritative valuation is incomplete until NAV data is refreshed for "
                + ", ".join(facts.missing_nav_fund_codes)
                + "."
            )

        if facts.top_weight_positions:
            largest_position = facts.top_weight_positions[0]
            if (
                largest_position.weight_ratio is not None
                and largest_position.weight_ratio >= HIGH_CONCENTRATION_RATIO
            ):
                risks.append(
                    f"{largest_position.fund_name} is above the current concentration watch line "
                    f"at {format_ratio_as_percent(largest_position.weight_ratio)}."
                )

        if (
            facts.max_drawdown_ratio is not None
            and facts.max_drawdown_ratio <= SEVERE_DRAWDOWN_RATIO
        ):
            risks.append(
                f"Period drawdown reached {format_ratio_as_percent(facts.max_drawdown_ratio)}, "
                "which is large enough to warrant a closer position-level review."
            )

        if facts.period_return_ratio is not None and facts.period_return_ratio < Decimal("0"):
            risks.append(
                "The requested-period return finished negative, so recent weakness should be "
                "reviewed before changing the allocation."
            )

        if not risks:
            risks.append(
                "No urgent risk flag was triggered by the current deterministic fact set, but "
                "the weekly window should still be monitored for concentration drift."
            )
        return risks

    def _build_recommendations(
        self,
        facts: WeeklyReviewFacts,
        risks_and_concerns: list[str],
    ) -> list[str]:
        recommendations: list[str] = []
        if facts.missing_nav_fund_codes:
            recommendations.append(
                "Refresh the missing NAV data first so the next weekly review can rely on a "
                "complete authoritative valuation set."
            )

        if facts.top_weight_positions:
            largest_position = facts.top_weight_positions[0]
            if (
                largest_position.weight_ratio is not None
                and largest_position.weight_ratio >= HIGH_CONCENTRATION_RATIO
            ):
                recommendations.append(
                    f"Check whether the current weight in {largest_position.fund_name} still "
                    "matches the intended allocation policy before the next review."
                )

        if facts.top_laggards:
            top_laggard = facts.top_laggards[0]
            recommendations.append(
                f"Monitor {top_laggard.fund_name} for another week before drawing a stronger "
                "conclusion from a single review window."
            )

        if not recommendations:
            recommendations.append(
                "Keep the current allocation under observation and revisit only after another "
                "complete weekly evidence set is available."
            )

        if risks_and_concerns and "No urgent risk flag" in risks_and_concerns[0]:
            recommendations.append(
                "Use the next weekly run to confirm that concentration and drawdown stay within "
                "the same range."
            )
        return recommendations

    def _build_open_questions(self, facts: WeeklyReviewFacts) -> list[str]:
        questions: list[str] = []
        if facts.missing_nav_fund_codes:
            questions.append(
                "When can the missing NAV coverage be refreshed so the report can be treated as "
                "complete?"
            )

        if facts.top_weight_positions:
            largest_position = facts.top_weight_positions[0]
            questions.append(
                f"Does the current weight in {largest_position.fund_name} still match the "
                "portfolio's intended risk posture?"
            )

        if facts.period_return_ratio is not None and facts.period_return_ratio < Decimal("0"):
            questions.append(
                "Was the weekly weakness broad across the portfolio, or concentrated in a small "
                "number of holdings?"
            )

        if not questions:
            questions.append(
                "Is there any upcoming transaction or allocation change that the next review "
                "window should account for?"
            )
        return questions

    def _describe_position_weight(self, position: ReviewPositionFact) -> str:
        if position.weight_ratio is None:
            return f"{position.fund_name} (weight unavailable)"
        return f"{position.fund_name} ({format_ratio_as_percent(position.weight_ratio)})"


def load_prompt_definition(prompt_name: str) -> PromptDefinition:
    """Load an agent prompt from the dedicated prompts directory."""
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / prompt_name
    return PromptDefinition(
        name=prompt_name,
        path=prompt_path,
        content=prompt_path.read_text(encoding="utf-8"),
    )


def format_money(value: Decimal) -> str:
    """Format money values for operator-facing agent output."""
    return f"{value:,.4f}"


def format_ratio_as_percent(value: Decimal) -> str:
    """Format ratio values as signed percentages."""
    percentage = value * Decimal("100")
    return f"{percentage:+.2f}%"


__all__ = [
    "ManualReviewAgent",
    "PromptDefinition",
    "ReviewAgent",
    "ReviewAgentOutput",
    "ReviewPositionFact",
    "WeeklyReviewFacts",
    "format_money",
    "format_ratio_as_percent",
    "load_prompt_definition",
]
