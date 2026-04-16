"""Manual ChallengerAgent implementation."""

from __future__ import annotations

import re

from fund_manager.agents.runtime.shared import PromptDefinition, load_prompt_definition
from fund_manager.agents.runtime.strategy_agent import (
    LOW_CONFIDENCE,
    MEDIUM_CONFIDENCE,
)
from fund_manager.core.ai_artifacts import ChallengerOutput, StrategyProposalOutput
from fund_manager.core.fact_packs import StrategyDebateFacts


class ManualChallengerAgent:
    """Deterministic placeholder ChallengerAgent for the debate workflow."""

    def __init__(
        self,
        *,
        prompt_name: str = "challenger_agent.md",
    ) -> None:
        # Placeholder manual runtime until a critique-focused challenger agent is wired in.
        self._prompt = load_prompt_definition(prompt_name)

    @property
    def agent_name(self) -> str:
        return "ChallengerAgent"

    @property
    def model_name(self) -> str:
        return "manual-challenger-agent-v1"

    @property
    def prompt(self) -> PromptDefinition:
        return self._prompt

    def challenge(
        self,
        facts: StrategyDebateFacts,
        proposal: StrategyProposalOutput,
    ) -> ChallengerOutput:
        """Critique the proposal with bounded, evidence-aware counterarguments."""
        critique_points = tuple(self._build_critique_points(facts, proposal))
        validate_critiques_distinct_from_proposal(proposal, critique_points)

        return ChallengerOutput(
            summary=self._build_summary(facts, proposal),
            critique_points=critique_points,
            evidence_gaps=tuple(self._build_evidence_gaps(facts, proposal)),
            counterarguments=tuple(self._build_counterarguments(facts, proposal)),
            confidence_level=LOW_CONFIDENCE
            if facts.missing_nav_fund_codes
            else MEDIUM_CONFIDENCE,
        )

    def _build_summary(
        self,
        facts: StrategyDebateFacts,
        proposal: StrategyProposalOutput,
    ) -> str:
        if facts.missing_nav_fund_codes:
            return (
                "The proposal is directionally cautious, but it should be even more restrained "
                "because the evidence base is incomplete."
            )
        return (
            "The proposal identifies real issues, but it still needs to defend why the current "
            "evidence is strong enough for its stated confidence and priorities."
        )

    def _build_critique_points(
        self,
        facts: StrategyDebateFacts,
        proposal: StrategyProposalOutput,
    ) -> list[str]:
        critique_points: list[str] = []
        if facts.valuation_point_count < 2:
            critique_points.append(
                "The proposal leans on a review window that still lacks enough valuation points "
                "for a robust period comparison."
            )
        if facts.missing_nav_fund_codes:
            critique_points.append(
                "The proposal should avoid implying a portfolio-wide call while NAV coverage is "
                "still incomplete."
            )
        if proposal.confidence_level != LOW_CONFIDENCE:
            critique_points.append(
                "The stated confidence may be too strong relative to the limited evidence and "
                "should be defended more carefully."
            )
        if facts.top_laggards:
            critique_points.append(
                "The proposal does not fully explain whether the weakest holding reflects a "
                "broad portfolio issue or a single-position problem."
            )
        if not critique_points:
            critique_points.append(
                "The proposal is cautious, but it still assumes the latest trend is meaningful "
                "without proving that it will persist beyond one review window."
            )
        return critique_points

    def _build_evidence_gaps(
        self,
        facts: StrategyDebateFacts,
        proposal: StrategyProposalOutput,
    ) -> list[str]:
        evidence_gaps = [
            (
                "The current evidence does not include target allocation bands or a formal "
                "rebalance threshold."
            ),
        ]
        if facts.valuation_point_count < 3:
            evidence_gaps.append(
                "The valuation window is short, so recent performance may be noisy rather than "
                "durable."
            )
        if facts.top_gainers and facts.top_laggards:
            evidence_gaps.append(
                "The proposal lacks a breadth check showing whether gains and losses were "
                "concentrated."
            )
        if proposal.proposed_actions:
            evidence_gaps.append(
                "The proposal does not quantify what would change the recommendation at the "
                "next review."
            )
        return evidence_gaps

    def _build_counterarguments(
        self,
        facts: StrategyDebateFacts,
        proposal: StrategyProposalOutput,
    ) -> list[str]:
        counterarguments: list[str] = []
        if facts.missing_nav_fund_codes:
            counterarguments.append(
                "A wait-for-complete-data stance may be safer than acting on a partially "
                "valued portfolio."
            )
        if facts.top_weight_positions:
            counterarguments.append(
                "Concentration review may matter more than recent return direction when one "
                "holding dominates."
            )
        if proposal.proposed_actions:
            counterarguments.append(
                "Maintaining a pure monitoring stance could be more defensible until another "
                "full review window confirms the trend."
            )
        return counterarguments


def validate_critiques_distinct_from_proposal(
    proposal: StrategyProposalOutput,
    critique_points: tuple[str, ...],
) -> None:
    """Fail fast if the challenger output collapses into proposal restatement."""
    proposal_texts = {_normalize_text(proposal.thesis)}
    proposal_texts.update(_normalize_text(action.action) for action in proposal.proposed_actions)

    normalized_critiques = tuple(_normalize_text(point) for point in critique_points)
    if not normalized_critiques:
        msg = "Challenger critique must contain at least one critique point."
        raise ValueError(msg)

    if all(
        any(
            critique == proposal_text
            or critique in proposal_text
            or proposal_text in critique
            for proposal_text in proposal_texts
        )
        for critique in normalized_critiques
    ):
        msg = "Challenger critique must not restate the proposal."
        raise ValueError(msg)


def _normalize_text(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


__all__ = [
    "ManualChallengerAgent",
    "validate_critiques_distinct_from_proposal",
]
