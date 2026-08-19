from __future__ import annotations

import pytest
from pydantic import ValidationError

from launch_os_v11.analytics.contracts import Phase6CheckpointSpec, TypedThreshold
from launch_os_v11.connectors.telegram_observation import FakeTelegramObservationConnector
from launch_os_v11.runtime.contracts import (
    EXECUTABLE_JOB_TYPES,
    JOB_TYPE_ANALYTICS_CALCULATE_METRIC_VERSION,
    JOB_TYPE_ANALYTICS_NORMALIZE_CONNECTOR_OBSERVATION,
    JOB_TYPE_CONNECTOR_TELEGRAM_OBSERVE_UPDATES,
    JOB_TYPE_LEARNING_INTERPRET_CHECKPOINT,
    JOB_TYPE_LEARNING_RUN_GOVERNED,
)


def test_phase6_checkpoint_contract_is_typed_and_hash_stable() -> None:
    spec = _spec()
    repeated = _spec()

    assert spec.contract_hash() == repeated.contract_hash()
    assert len(spec.contract_hash()) == 64
    assert spec.metric_key == "telegram_reaction_changes"


def test_phase6_checkpoint_rejects_non_deterministic_threshold_shape() -> None:
    with pytest.raises(ValidationError):
        Phase6CheckpointSpec(
            window_seconds=30,
            grace_seconds=0,
            success=TypedThreshold(operator="GTE", value=2),
            weak_signal=TypedThreshold(operator="LTE", value=1),
            failure=TypedThreshold(operator="EQ", value=0),
            next_action_on_success="continue",
            next_action_on_weak_signal="observe",
            next_action_on_failure="inspect",
        )


def test_phase6_runtime_jobs_are_executable() -> None:
    required = {
        JOB_TYPE_CONNECTOR_TELEGRAM_OBSERVE_UPDATES,
        JOB_TYPE_ANALYTICS_NORMALIZE_CONNECTOR_OBSERVATION,
        JOB_TYPE_ANALYTICS_CALCULATE_METRIC_VERSION,
        JOB_TYPE_LEARNING_INTERPRET_CHECKPOINT,
        JOB_TYPE_LEARNING_RUN_GOVERNED,
    }
    assert required.issubset(EXECUTABLE_JOB_TYPES)


def test_fake_telegram_observation_respects_cursor_and_allowlist() -> None:
    connector = FakeTelegramObservationConnector(
        updates=[
            {
                "update_id": 9,
                "channel_post": {
                    "message_id": 1,
                    "date": 1,
                    "chat": {"id": -1},
                },
            },
            {
                "update_id": 10,
                "message_reaction": {
                    "message_id": 1,
                    "date": 2,
                    "chat": {"id": -1},
                },
            },
        ]
    )

    updates = connector.get_updates(
        offset=10,
        allowed_updates=("message_reaction",),
        timeout_seconds=0,
    )

    assert [update["update_id"] for update in updates] == [10]
    assert connector.calls == [
        {
            "offset": 10,
            "allowed_updates": ("message_reaction",),
            "timeout_seconds": 0,
        }
    ]


def _spec() -> Phase6CheckpointSpec:
    return Phase6CheckpointSpec(
        window_seconds=30,
        grace_seconds=0,
        success=TypedThreshold(operator="GTE", value=2),
        weak_signal=TypedThreshold(operator="GTE", value=1),
        failure=TypedThreshold(operator="EQ", value=0),
        next_action_on_success="continue",
        next_action_on_weak_signal="observe",
        next_action_on_failure="inspect",
    )
