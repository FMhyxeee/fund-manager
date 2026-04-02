"""JudgeAgent runtime contracts and the first manual implementation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from fund_manager.agents.runtime.challenger_agent import ChallengerOutput
from fund_manager.agents.runtime.review_agent import PromptDefinition, load_prompt_definition
from fund_manager.agents.runtime.strategy_agent import (
    LOW_CONFIDENCE,
    MEDIUM_CONFIDENCE,
    StrategyAction,
    StrategyDebateFacts,
    StrategyProposalOutput,
)

LOW_CONFIDENCE_SCORE = Decimal("0.3500")
MEDIUM_CONFIDENCE_SCORE = Decimal("0.6500")


@dataclass(frozen=True)
class JudgeOutput:
    """Structured final recommendation produced by JudgeAgent."""

    summary: str
    thesis: str
    evidence: tuple[str, ...]
    proposed_actions: tuple[StrategyAction, ...]
    counterarguments: tuple[str, ...]
    final_judgment: str
    confidence_level: str
    confidence_score: Decimal


class JudgeAgent(Protocol):
    """Runtime contract for a bounded judge agent."""

    @property
    def agent_name(self) -> str:
        """Human-readable logical agent name."""

    @property
    def model_name(self) -> str | None:
        """Concrete runtime identifier when available."""

    @property
    def prompt(self) -> PromptDefinition:
        """Prompt definition used by the runtime."""

    def judge(
        self,
        facts: StrategyDebateFacts,
        proposal: StrategyProposalOutput,
        challenge: ChallengerOutput,
    ) -> JudgeOutput:
        """Synthesize the proposal and critique into a final recommendation."""


class ManualJudgeAgent:
    """Deterministic placeholder JudgeAgent for the debate workflow."""

    def __init__(
        self,
        *,
        prompt_name: str = "judge_agent.md",
    ) -> None:
        self._prompt = load_prompt_definition(prompt_name)

    @property
    def agent_name(self) -> str:
        return "JudgeAgent"

    @property
    def model_name(self) -> str:
        return "manual-judge-agent-v1"

    @property
    def prompt(self) -> PromptDefinition:
        return self._prompt

    def judge(
        self,
        facts: StrategyDebateFacts,
        proposal: StrategyProposalOutput,
        challenge: ChallengerOutput,
    ) -> JudgeOutput:
        """Produce a final recommendation after weighing the critique."""
        confidence_level = LOW_CONFIDENCE if facts.missing_nav_fund_codes else MEDIUM_CONFIDENCE
        confidence_score = (
            LOW_CONFIDENCE_SCORE if confidence_level == LOW_CONFIDENCE else MEDIUM_CONFIDENCE_SCORE
        )
        final_judgment = (
            "defer_until_complete_data"
            if facts.missing_nav_fund_codes
            else "monitor_with_concentration_review"
        )
        counterarguments = tuple(dict.fromkeys(challenge.counterarguments + challenge.critique_points))

        return JudgeOutput(
            summary=self._build_summary(facts, challenge, final_judgment),
            thesis=self._build_thesis(facts, proposal),
            evidence=proposal.evidence,
            proposed_actions=proposal.proposed_actions,
            counterarguments=counterarguments,
            final_judgment=final_judgment,
            confidence_level=confidence_level,
            confidence_score=confidence_score,
        )

    def _build_summary(
        self,
        facts: StrategyDebateFacts,
        challenge: ChallengerOutput,
        final_judgment: str,
    ) -> str:
        if final_judgment == "defer_until_complete_data":
            return (
                "The debate supports deferring any stronger strategy shift until the portfolio "
                "has complete authoritative valuation coverage."
            )
        if challenge.critique_points:
            return (
                "The final recommendation keeps the proposal's core caution but absorbs the "
                "challenger's concerns by lowering certainty and emphasizing review over action."
            )
        return (
            "The final recommendation follows the proposal because no stronger counterargument "
            "outweighed the current evidence."
        )

    def _build_thesis(
        self,
        facts: StrategyDebateFacts,
        proposal: StrategyProposalOutput,
    ) -> str:
        if facts.missing_nav_fund_codes:
            return (
                "Wait for complete NAV coverage, then rerun the debate before making any stronger "
                "allocation recommendation."
            )
        return proposal.thesis


__all__ = [
    "JudgeAgent",
    "JudgeOutput",
    "LOW_CONFIDENCE_SCORE",
    "MEDIUM_CONFIDENCE_SCORE",
    "ManualJudgeAgent",
]
