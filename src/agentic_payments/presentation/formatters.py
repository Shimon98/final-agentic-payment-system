"""Stable, path-aware, secret-safe CLI formatting."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from math import isfinite
from typing import Any

from pydantic import BaseModel

from agentic_payments.application import AgentResult
from agentic_payments.bootstrap import ApplicationContainer, ApplicationState

_ALLOWED_FLOAT_FIELDS = {
    "confidence",
    "route_confidence",
    "confidence_threshold",
}
_PROHIBITED_KEY_PARTS = (
    "api_key",
    "authorization",
    "password",
    "secret",
    "token",
    "prompt",
)
_COMPLETE_PHONE = re.compile(r"(?<![A-Za-z0-9])\+?\d{7,15}(?![A-Za-z0-9])")


def _safe_value(value: Any, *, path: tuple[str | None, ...]) -> object:
    if isinstance(value, BaseException):
        raise TypeError("exceptions cannot be formatted")
    if isinstance(value, (ApplicationState, ApplicationContainer)):
        raise TypeError("application state and containers cannot be formatted")
    if isinstance(value, str):
        return _COMPLETE_PHONE.sub("[REDACTED]", value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        field_name = path[-1] if path else None
        if not isfinite(value):
            raise ValueError("non-finite floats cannot be formatted")
        if field_name not in _ALLOWED_FLOAT_FIELDS:
            raise ValueError("float values are allowed only for approved confidence fields")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Decimal values must be finite")
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return _safe_value(value.value, path=path)
    if isinstance(value, BaseModel):
        return _safe_value(value.model_dump(mode="json"), path=path)
    if is_dataclass(value) and not isinstance(value, type):
        return _safe_value(asdict(value), path=path)
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise TypeError("mapping keys must be strings")
            lowered = key.lower()
            if any(marker in lowered for marker in _PROHIBITED_KEY_PARTS):
                raise ValueError("mapping contains a prohibited key")
            if "phone" in lowered:
                result[key] = "[REDACTED]"
            else:
                result[key] = _safe_value(nested, path=(*path, key))
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, path=(*path, None)) for item in value]
    raise TypeError(f"unsupported safe-format value: {type(value).__name__}")


def to_safe_json_value(
    value: object,
) -> object:
    """Return a recursively copied value suitable for safe JSON output."""

    return _safe_value(value, path=())


def format_agent_result(
    result: AgentResult,
) -> str:
    """Format one validated agent result as stable UTF-8 JSON."""

    if not isinstance(result, AgentResult):
        raise TypeError("result must be AgentResult")
    payload = to_safe_json_value(
        {
            "agent_name": result.agent_name,
            "confidence": result.confidence,
            "output": result.output,
            "metadata": result.metadata,
        }
    )
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )


def format_status(
    container: ApplicationContainer,
) -> str:
    """Display only configuration labels and aggregate counts."""

    if not isinstance(container, ApplicationContainer):
        raise TypeError("container must be ApplicationContainer")
    state = container.snapshot()
    payload = {
        "app_environment": container.settings.app_env,
        "llm_provider": container.settings.llm_provider,
        "llm_router_enabled": container.llm_runtime is not None,
        "user_count": len(state.users),
        "wallet_count": len(state.wallets),
        "transaction_count": len(state.transactions),
        "payment_request_count": len(state.payment_requests),
        "pending_audit_count": len(state.pending_audit_events),
        "last_memory_action": state.memory.last_action,
        "startup_warning_count": len(container.startup_warnings),
    }
    return json.dumps(
        to_safe_json_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )


def format_help() -> str:
    """Return canonical English and Hebrew examples for all supported intents."""

    return """Agentic Payments — educational simulation / סימולציית תשלומים לימודית

createUser / יצירת משתמש:
  createUser name="Alice Cohen" phone=05XXXXXXXX initial_balance=1000.00
checkBalance / בדיקת יתרה:
  checkBalance user_id=USR-001
transferMoney / העברת כסף:
  transferMoney sender_id=USR-001 receiver_id=USR-002 amount=125.00
requestPayment / בקשת תשלום:
  requestPayment requester_id=USR-002 payer_id=USR-001 amount=50.00
approvePayment / אישור בקשת תשלום:
  approvePayment request_id=REQ-001
rejectPayment / דחיית בקשת תשלום:
  rejectPayment request_id=REQ-001
showTransactions / הצגת עסקאות:
  showTransactions user_id=USR-001
fraudCheck / בדיקת הונאה:
  fraudCheck transaction_id=TXN-001
securityReview / בדיקת אבטחה:
  securityReview transaction_id=TXN-001
explainLastAction / הסבר הפעולה האחרונה:
  explainLastAction

Interactive commands / פקודות אינטראקטיביות:
  /help  /status  /flush  /reset  /exit
"""
