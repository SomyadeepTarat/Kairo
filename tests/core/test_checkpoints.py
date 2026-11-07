"""Corrupt/unsupported continuation input must never become executable context."""

import json

import pytest
from kairo_core.checkpoints import KernelSnapshot


def test_snapshot_roundtrip_preserves_context() -> None:
    payload = {
        "messages": [
            {"role": "system", "content": "instructions"},
            {"role": "user", "content": "task"},
        ],
        "next_step": 2,
        "remaining_seconds": 10.0,
    }
    state = KernelSnapshot.model_validate_json(json.dumps(payload))
    assert KernelSnapshot.model_validate_json(state.model_dump_json()) == state
    assert state.version == 1 and state.next_step == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"version": 2},
        {"next_step": 0},
        {"remaining_seconds": -1},
        {"remaining_seconds": float("inf")},
        {"final_output": " "},
        {
            "messages": [
                {"role": "assistant", "content": "bad"},
                {"role": "user", "content": "task"},
            ]
        },
    ],
)
def test_invalid_snapshots_are_rejected(changes: dict[str, object]) -> None:
    payload: dict[str, object] = {
        "messages": [
            {"role": "system", "content": "instructions"},
            {"role": "user", "content": "task"},
        ],
        "next_step": 1,
        "remaining_seconds": 10.0,
    }
    payload.update(changes)
    with pytest.raises(ValueError):
        KernelSnapshot.model_validate_json(json.dumps(payload))
