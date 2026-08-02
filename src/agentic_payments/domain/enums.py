"""Enumerations used by the deterministic payment domain."""

from __future__ import annotations

from enum import Enum


class TransactionStatus(str, Enum):  # noqa: UP042 - exact public API requires str, Enum.
    """Lifecycle status of a payment transaction."""

    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FLAGGED = "FLAGGED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class PaymentRequestStatus(str, Enum):  # noqa: UP042 - exact public API requires str, Enum.
    """Lifecycle status of a payment request."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RiskLevel(str, Enum):  # noqa: UP042 - exact public API requires str, Enum.
    """Deterministic fraud-risk classification."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Intent(str, Enum):  # noqa: UP042 - exact public API requires str, Enum.
    """Supported user intents."""

    CREATE_USER = "createUser"
    CHECK_BALANCE = "checkBalance"
    TRANSFER_MONEY = "transferMoney"
    REQUEST_PAYMENT = "requestPayment"
    APPROVE_PAYMENT = "approvePayment"
    REJECT_PAYMENT = "rejectPayment"
    SHOW_TRANSACTIONS = "showTransactions"
    FRAUD_CHECK = "fraudCheck"
    SECURITY_REVIEW = "securityReview"
    EXPLAIN_LAST_ACTION = "explainLastAction"
    UNKNOWN = "unknown"
