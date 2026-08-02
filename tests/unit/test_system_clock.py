"""Tests for the approved concrete UTC system clock."""

from datetime import UTC, datetime

from agentic_payments.application import Clock
from agentic_payments.infrastructure import SystemClock


def test_system_clock_satisfies_clock_protocol() -> None:
    assert isinstance(SystemClock(), Clock)


def test_system_clock_returns_fresh_aware_utc_time_within_bounds() -> None:
    clock = SystemClock()
    before = datetime.now(UTC)
    first = clock.now()
    second = clock.now()
    after = datetime.now(UTC)

    assert first.tzinfo is UTC
    assert second.tzinfo is UTC
    assert before <= first <= second <= after
