"""UUID-based identifiers for concrete application infrastructure."""

import uuid


class UuidIdGenerator:
    """Generate practically unique prefixed identifiers without mutable counters."""

    @staticmethod
    def _new(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex}"

    def new_user_id(self) -> str:
        """Return a new user identifier."""

        return self._new("USR")

    def new_transaction_id(self) -> str:
        """Return a new transaction identifier."""

        return self._new("TXN")

    def new_payment_request_id(self) -> str:
        """Return a new payment-request identifier."""

        return self._new("REQ")

    def new_audit_event_id(self) -> str:
        """Return a new audit-event identifier."""

        return self._new("AUD")

    def new_correlation_id(self) -> str:
        """Return a new correlation identifier."""

        return self._new("COR")
