"""Repository helpers for append-only agent execution logs."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from fund_manager.storage.models import AgentDebateLog


class AgentDebateLogRepository:
    """Persist workflow trace records for agent executions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        *,
        run_id: str,
        workflow_name: str,
        agent_name: str,
        portfolio_id: int | None = None,
        model_name: str | None = None,
        input_summary: str | None = None,
        output_summary: str | None = None,
        tool_calls_json: list[dict[str, Any]] | dict[str, Any] | None = None,
        trace_reference: str | None = None,
    ) -> AgentDebateLog:
        """Append one agent execution log row."""
        debate_log = AgentDebateLog(
            portfolio_id=portfolio_id,
            run_id=run_id,
            workflow_name=workflow_name,
            agent_name=agent_name,
            model_name=model_name,
            input_summary=input_summary,
            output_summary=output_summary,
            tool_calls_json=tool_calls_json,
            trace_reference=trace_reference,
        )
        self._session.add(debate_log)
        self._session.flush()
        return debate_log
