"""Repository helpers for append-only system events."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from fund_manager.storage.models import SystemEventLog


class SystemEventLogRepository:
    """Persist workflow lifecycle events for later traceability."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        *,
        event_type: str,
        status: str,
        portfolio_id: int | None = None,
        run_id: str | None = None,
        workflow_name: str | None = None,
        event_message: str | None = None,
        payload_json: dict[str, Any] | list[Any] | None = None,
    ) -> SystemEventLog:
        """Append one workflow or system event row."""
        system_event_log = SystemEventLog(
            portfolio_id=portfolio_id,
            run_id=run_id,
            workflow_name=workflow_name,
            event_type=event_type,
            status=status,
            event_message=event_message,
            payload_json=payload_json,
        )
        self._session.add(system_event_log)
        self._session.flush()
        return system_event_log
