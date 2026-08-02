"""Concrete UTC system clock."""

from datetime import datetime, timezone


class SystemClock:
    """Return a fresh timezone-aware UTC timestamp for each call."""

    def now(self) -> datetime:
        """Return the current UTC system time."""

        return datetime.now(timezone.utc)  # noqa: UP017 - approved public clock contract
