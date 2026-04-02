"""Workflow orchestration modules."""

from fund_manager.agents.workflows.strategy_debate import (
    MAX_HIGHLIGHT_POSITIONS as STRATEGY_DEBATE_MAX_HIGHLIGHT_POSITIONS,
    WORKFLOW_NAME as STRATEGY_DEBATE_WORKFLOW_NAME,
    StrategyDebateWorkflow,
    StrategyDebateWorkflowResult,
    build_strategy_debate_run_id,
    run_strategy_debate,
)
from fund_manager.agents.workflows.weekly_review import (
    WORKFLOW_NAME,
    WeeklyReviewWorkflow,
    WeeklyReviewWorkflowResult,
    build_weekly_review_run_id,
    run_manual_weekly_review,
    serialize_for_json,
)

__all__ = [
    "STRATEGY_DEBATE_MAX_HIGHLIGHT_POSITIONS",
    "STRATEGY_DEBATE_WORKFLOW_NAME",
    "StrategyDebateWorkflow",
    "StrategyDebateWorkflowResult",
    "WORKFLOW_NAME",
    "WeeklyReviewWorkflow",
    "WeeklyReviewWorkflowResult",
    "build_strategy_debate_run_id",
    "build_weekly_review_run_id",
    "run_strategy_debate",
    "run_manual_weekly_review",
    "serialize_for_json",
]
