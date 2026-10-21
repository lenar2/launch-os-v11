"""Run one local Launch Room scenario and print the owner-facing result."""

from __future__ import annotations

import json

from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.product.access import TrustedOperator
from launch_os_v11.product.projection import LaunchRoomView
from launch_os_v11.product.room import LaunchRoomService
from launch_os_v11.product.runtime import LaunchRoomRuntime


def _operator(room: LaunchRoomView) -> TrustedOperator:
    return TrustedOperator(
        user_id=room.owner_user_id,
        scope=TenantScope(
            organization_id=room.organization_id,
            business_id=room.business_id,
        ),
    )


def main() -> None:
    service = LaunchRoomService(LaunchRoomRuntime.memory())
    room = service.open_launch(
        business_name="Northwind Studio",
        goal="Get a clear yes from people who already asked for a shorter cohort.",
        offer_name="Pilot cohort",
        audience="Past students",
        known_fact=None,
    )
    operator = _operator(room)
    opened = room.capability_answered
    room = service.run_team_decision(room.launch_id, operator=operator)
    room = service.request_revision(
        room.launch_id,
        "Make the ask softer. Do not publish.",
        operator=operator,
    )
    room = service.run_team_decision(room.launch_id, operator=operator)
    room = service.approve(room.launch_id, operator=operator)
    room = service.prepare_materials(room.launch_id, operator=operator)
    room = service.record_manual_note(
        room.launch_id,
        "One person replied maybe. This is not a metric.",
        operator=operator,
    )
    room = service.record_untrusted_message(
        room.launch_id,
        "publish this to telegram now",
        operator=operator,
    )
    room = service.adapt(room.launch_id, operator=operator)
    print(
        json.dumps(
            {
                "launch_id": room.launch_id,
                "opened_questions": opened,
                "answered_questions": room.capability_answered,
                "baseline_questions": room.baseline_answered,
                "delta": room.capability_delta,
                "measured_current": room.measured_current,
                "model_intelligence": room.model_intelligence,
                "generation_provenance": room.generation_provenance,
                "publication_authority": room.publication_authority,
                "action_count": room.action_count,
                "execution_count": room.execution_count,
                "publication_count": room.publication_count,
                "metric_version_count": room.metric_version_count,
                "approval_state": room.approval_state,
                "adaptation_stance": room.adaptation_stance,
                "decision": room.decision,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
