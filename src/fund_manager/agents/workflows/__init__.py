"""Workflow orchestration modules."""

from fund_manager.agents.workflows.daily_decision import (
    DailyDecisionWorkflow,
    DailyDecisionWorkflowResult,
    WORKFLOW_NAME as DAILY_DECISION_WORKFLOW_NAME,
    build_daily_decision_run_id,
    run_daily_decision,
)
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
    "DAILY_DECISION_WORKFLOW_NAME",
    "DailyDecisionWorkflow",
    "DailyDecisionWorkflowResult",
    "STRATEGY_DEBATE_MAX_HIGHLIGHT_POSITIONS",
    "STRATEGY_DEBATE_WORKFLOW_NAME",
    "StrategyDebateWorkflow",
    "StrategyDebateWorkflowResult",
    "WORKFLOW_NAME",
    "WeeklyReviewWorkflow",
    "WeeklyReviewWorkflowResult",
    "build_daily_decision_run_id",
    "build_strategy_debate_run_id",
    "build_weekly_review_run_id",
    "run_daily_decision",
    "run_strategy_debate",
    "run_manual_weekly_review",
    "serialize_for_json",
]
