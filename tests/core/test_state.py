"""All lifecycle edges, independently specified from the M0 transition table."""

from typing import cast

import pytest
from kairo_core.state import InvalidTransition, RunStatus, transition

S = RunStatus
# This is the specification's table, not imported implementation data.
EXPECTED = {
    S.CREATED: {S.QUEUED, S.FAILED, S.CANCELLED},
    S.QUEUED: {S.RUNNING, S.FAILED, S.CANCELLED},
    S.RUNNING: {
        S.WAITING_FOR_TOOL,
        S.WAITING_FOR_APPROVAL,
        S.PAUSED,
        S.COMPLETED,
        S.FAILED,
        S.CANCELLED,
    },
    S.WAITING_FOR_TOOL: {S.RUNNING, S.FAILED, S.CANCELLED},
    S.WAITING_FOR_APPROVAL: {S.RUNNING, S.FAILED, S.CANCELLED},
    S.PAUSED: {S.QUEUED, S.FAILED, S.CANCELLED},
    S.COMPLETED: set(),
    S.FAILED: set(),
    S.CANCELLED: set(),
}


@pytest.mark.parametrize("source", list(S))
@pytest.mark.parametrize("target", list(S))
def test_every_lifecycle_edge(source: RunStatus, target: RunStatus) -> None:
    if target in EXPECTED[source]:
        assert transition(source, target) is target
    else:
        with pytest.raises(InvalidTransition):
            transition(source, target)


def test_raw_strings_do_not_bypass_enum_contract() -> None:
    with pytest.raises(InvalidTransition):
        transition(cast(RunStatus, "CREATED"), S.QUEUED)
