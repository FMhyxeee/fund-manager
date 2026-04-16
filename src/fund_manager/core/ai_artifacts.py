"""Typed AI artifact contracts persisted or transported by workflows."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


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


@dataclass(frozen=True)
class StrategyAction:
    """One evidence-backed strategy action candidate."""

    action: str
    rationale: str
    evidence_refs: tuple[str, ...]
    priority: str


@dataclass(frozen=True)
class StrategyProposalOutput:
    """Structured proposal produced by StrategyAgent."""

    summary: str
    thesis: str
    evidence: tuple[str, ...]
    proposed_actions: tuple[StrategyAction, ...]
    risks: tuple[str, ...]
    confidence_level: str


@dataclass(frozen=True)
class ChallengerOutput:
    """Structured critique produced by ChallengerAgent."""

    summary: str
    critique_points: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    counterarguments: tuple[str, ...]
    confidence_level: str


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


__all__ = [
    "ChallengerOutput",
    "JudgeOutput",
    "ReviewAgentOutput",
    "StrategyAction",
    "StrategyProposalOutput",
]
