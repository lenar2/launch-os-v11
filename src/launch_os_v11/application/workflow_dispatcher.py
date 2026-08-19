from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.orm import Session

from launch_os_v11.runtime.clock import Clock
from launch_os_v11.runtime.contracts import RuntimeJobContext
from launch_os_v11.runtime.errors import PermanentJobError
from launch_os_v11.runtime.handlers import JobHandler


class WorkflowAdvanceDispatcher:
    """Route durable workflow jobs without owning business reasoning."""

    def __init__(
        self,
        *,
        decision_handler: JobHandler,
        production_handler: JobHandler,
    ) -> None:
        self._decision_handler = decision_handler
        self._production_handler = production_handler

    def handle(
        self,
        *,
        context: RuntimeJobContext,
        payload: Mapping[str, object],
        session: Session,
        clock: Clock,
    ) -> None:
        has_decision = isinstance(payload.get("workflow_id"), str)
        has_production = isinstance(payload.get("production_workflow_id"), str)
        if has_decision == has_production:
            raise PermanentJobError(
                "workflow.advance must bind exactly one governed workflow kind"
            )
        if has_production:
            self._production_handler.handle(
                context=context,
                payload=payload,
                session=session,
                clock=clock,
            )
            return
        self._decision_handler.handle(
            context=context,
            payload=payload,
            session=session,
            clock=clock,
        )
