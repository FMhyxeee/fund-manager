"""Runtime-facing agent protocols for the orchestration layer."""

from __future__ import annotations

from typing import Protocol

from fund_manager.agents.runtime.shared import PromptDefinition
from fund_manager.core.ai_artifacts import (
    ChallengerOutput,
    JudgeOutput,
    ReviewAgentOutput,
    StrategyProposalOutput,
)
from fund_manager.core.fact_packs import StrategyDebateFacts, WeeklyReviewFacts


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


class StrategyAgent(Protocol):
    """Runtime contract for a bounded strategy proposal agent."""

    @property
    def agent_name(self) -> str:
        """Human-readable logical agent name."""

    @property
    def model_name(self) -> str | None:
        """Concrete runtime identifier when available."""

    @property
    def prompt(self) -> PromptDefinition:
        """Prompt definition used by the runtime."""

    def propose(self, facts: StrategyDebateFacts) -> StrategyProposalOutput:
        """Produce a structured proposal from prepared facts only."""


class ChallengerAgent(Protocol):
    """Runtime contract for a bounded challenger agent."""

    @property
    def agent_name(self) -> str:
        """Human-readable logical agent name."""

    @property
    def model_name(self) -> str | None:
        """Concrete runtime identifier when available."""

    @property
    def prompt(self) -> PromptDefinition:
        """Prompt definition used by the runtime."""

    def challenge(
        self,
        facts: StrategyDebateFacts,
        proposal: StrategyProposalOutput,
    ) -> ChallengerOutput:
        """Critique a proposal using the same prepared facts only."""


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


__all__ = [
    "ChallengerAgent",
    "JudgeAgent",
    "ReviewAgent",
    "StrategyAgent",
]
