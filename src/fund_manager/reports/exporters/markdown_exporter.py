"""Markdown renderers for persisted review artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from fund_manager.core.ai_artifacts import ReviewAgentOutput
from fund_manager.core.fact_packs import WeeklyReviewFacts


@dataclass(frozen=True)
class WeeklyReviewMarkdownContext:
    """Render context for one weekly review markdown report."""

    facts: WeeklyReviewFacts
    review: ReviewAgentOutput
    run_id: str
    workflow_name: str
    trigger_source: str
    prompt_reference: str
    generated_at: datetime


class WeeklyReviewMarkdownExporter:
    """Render weekly review markdown using a dedicated Jinja template."""

    def __init__(self, *, template_dir: Path | None = None) -> None:
        resolved_template_dir = template_dir or Path(__file__).resolve().parent.parent / "templates"
        self._environment = Environment(
            loader=FileSystemLoader(str(resolved_template_dir)),
            autoescape=select_autoescape(default_for_string=False, disabled_extensions=("md",)),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._environment.filters["money"] = format_money
        self._environment.filters["ratio_percent"] = format_ratio_as_percent
        self._environment.filters["or_na"] = or_na

    def render(
        self,
        *,
        facts: WeeklyReviewFacts,
        review: ReviewAgentOutput,
        run_id: str,
        workflow_name: str,
        trigger_source: str,
        prompt_reference: str,
    ) -> str:
        """Render one markdown weekly review report."""
        template = self._environment.get_template("weekly_review.md.j2")
        context = WeeklyReviewMarkdownContext(
            facts=facts,
            review=review,
            run_id=run_id,
            workflow_name=workflow_name,
            trigger_source=trigger_source,
            prompt_reference=prompt_reference,
            generated_at=datetime.now(UTC),
        )
        return template.render(context=context).strip() + "\n"


def format_money(value: Decimal | None) -> str:
    """Format a money value or show N/A for incomplete valuations."""
    if value is None:
        return "N/A"
    return f"{value:,.4f}"


def format_ratio_as_percent(value: Decimal | None) -> str:
    """Format a ratio as a signed percentage or show N/A."""
    if value is None:
        return "N/A"
    percentage = value * Decimal("100")
    return f"{percentage:+.2f}%"


def or_na(value: Any) -> Any:
    """Replace empty-ish scalar values with N/A in the template."""
    if value in (None, "", (), []):
        return "N/A"
    return value


__all__ = [
    "WeeklyReviewMarkdownContext",
    "WeeklyReviewMarkdownExporter",
    "format_money",
    "format_ratio_as_percent",
]
