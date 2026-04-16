"""Shared runtime helpers for prompt loading and simple manual formatting."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class PromptDefinition:
    """Loaded prompt text plus its traceable file reference."""

    name: str
    path: Path
    content: str


def load_prompt_definition(prompt_name: str) -> PromptDefinition:
    """Load an agent prompt from the dedicated prompts directory."""
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / prompt_name
    return PromptDefinition(
        name=prompt_name,
        path=prompt_path,
        content=prompt_path.read_text(encoding="utf-8"),
    )


def format_money(value: Decimal) -> str:
    """Format money values for operator-facing manual agent output."""
    return f"{value:,.4f}"


def format_ratio_as_percent(value: Decimal) -> str:
    """Format ratio values as signed percentages."""
    percentage = value * Decimal("100")
    return f"{percentage:+.2f}%"


__all__ = [
    "PromptDefinition",
    "format_money",
    "format_ratio_as_percent",
    "load_prompt_definition",
]
