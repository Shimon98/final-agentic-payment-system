"""Deterministic English/Hebrew command router without model access."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from agentic_payments.agents.base import AgentContext, BaseAgent
from agentic_payments.application import AgentResult, RouterDecision
from agentic_payments.domain import Intent

_DECIMAL_PATTERN = re.compile(r"[+-]?(?:0|[1-9]\d*)(?:\.\d{1,2})?")


@dataclass(frozen=True, slots=True)
class _CommandSpec:
    intent: Intent
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    aliases: tuple[tuple[str, str], ...] = ()


_COMMANDS: dict[str, _CommandSpec] = {
    "createuser": _CommandSpec(
        Intent.CREATE_USER,
        ("name", "phone_number", "initial_balance"),
        aliases=(("phone", "phone_number"),),
    ),
    "checkbalance": _CommandSpec(Intent.CHECK_BALANCE, ("user_id",)),
    "transfermoney": _CommandSpec(
        Intent.TRANSFER_MONEY,
        ("sender_id", "receiver_id", "amount"),
    ),
    "requestpayment": _CommandSpec(
        Intent.REQUEST_PAYMENT,
        ("requester_id", "payer_id", "amount"),
    ),
    "approvepayment": _CommandSpec(Intent.APPROVE_PAYMENT, ("request_id",)),
    "rejectpayment": _CommandSpec(Intent.REJECT_PAYMENT, ("request_id",)),
    "showtransactions": _CommandSpec(Intent.SHOW_TRANSACTIONS, ("user_id",)),
    "fraudcheck": _CommandSpec(Intent.FRAUD_CHECK, ("transaction_id",)),
    "securityreview": _CommandSpec(
        Intent.SECURITY_REVIEW,
        (),
        optional=("transaction_id",),
    ),
    "explainlastaction": _CommandSpec(Intent.EXPLAIN_LAST_ACTION, ()),
}

_HEBREW_ALIASES = {
    "צורמשתמש": "createuser",
    "בדוקיתרה": "checkbalance",
    "העברכסף": "transfermoney",
    "בקששלום": "requestpayment",
    "אשרתשלום": "approvepayment",
    "דחהתשלום": "rejectpayment",
    "הצגעסקאות": "showtransactions",
    "בדיקתהונאה": "fraudcheck",
    "בדיקתאבטחה": "securityreview",
    "הסברפעולהאחרונה": "explainlastaction",
}

_MONEY_FIELDS = {"amount", "initial_balance"}


def _parse_decimal(value: str) -> Decimal | None:
    if _DECIMAL_PATTERN.fullmatch(value) is None:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _clarification(intent: Intent, parameters: dict[str, object], question: str) -> RouterDecision:
    return RouterDecision(
        intent=intent,
        parameters=parameters,
        confidence=0.60,
        requires_clarification=True,
        clarification_question=question,
    )


class RouterAgent(BaseAgent):
    """Classify only the explicitly supported deterministic command grammar."""

    def __init__(self, *, confidence_threshold: float = 0.80) -> None:
        if isinstance(confidence_threshold, bool) or not isinstance(
            confidence_threshold, (int, float)
        ):
            raise TypeError("confidence_threshold must be numeric and not bool")
        normalized = float(confidence_threshold)
        if not 0.0 <= normalized <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        self._confidence_threshold = normalized

    @property
    def name(self) -> str:
        """Return the stable router identity."""

        return "RouterAgent"

    def _result(self, decision: RouterDecision, mode: str) -> AgentResult:
        return AgentResult(
            agent_name=self.name,
            output=decision,
            confidence=decision.confidence,
            metadata={
                "mode": mode,
                "confidence_threshold": self._confidence_threshold,
                "below_threshold": decision.confidence < self._confidence_threshold,
            },
        )

    @staticmethod
    def _unknown() -> RouterDecision:
        return RouterDecision(
            intent=Intent.UNKNOWN,
            parameters={},
            confidence=0.0,
            requires_clarification=True,
            clarification_question="איזו פעולה נתמכת ברצונך לבצע?",
        )

    @staticmethod
    def _natural_transfer(text: str) -> RouterDecision | None:
        english = re.fullmatch(
            r"transfer\s+(\S+)(?:\s+ILS)?\s+from\s+(\S+)\s+to\s+(\S+)",
            text,
            flags=re.IGNORECASE,
        )
        hebrew = re.fullmatch(
            r"העבר\s+(\S+)(?:\s+שקלים)?\s+מ-\s*(\S+)\s+ל-\s*(\S+)",
            text,
        )
        match = english or hebrew
        if match is None:
            return None
        raw_amount, sender_id, receiver_id = match.groups()
        amount = _parse_decimal(raw_amount)
        safe_parameters: dict[str, object] = {
            "sender_id": sender_id,
            "receiver_id": receiver_id,
        }
        if amount is None:
            return _clarification(
                Intent.TRANSFER_MONEY,
                safe_parameters,
                "מהו סכום תקין להעברה?",
            )
        safe_parameters["amount"] = amount
        return RouterDecision(
            intent=Intent.TRANSFER_MONEY,
            parameters=safe_parameters,
            confidence=0.90,
        )

    @staticmethod
    def _canonical(text: str) -> RouterDecision | None:
        try:
            tokens = shlex.split(text)
        except ValueError:
            tokens = text.split()
        if not tokens:
            return None
        command_key = _HEBREW_ALIASES.get(tokens[0], tokens[0].lower())
        spec = _COMMANDS.get(command_key)
        if spec is None:
            return None

        alias_map = dict(spec.aliases)
        allowed = {*spec.required, *spec.optional}
        parsed: dict[str, object] = {}
        malformed = False
        for token in tokens[1:]:
            if "=" not in token:
                malformed = True
                continue
            raw_key, value = token.split("=", 1)
            key = alias_map.get(raw_key, raw_key)
            if key not in allowed or key in parsed or not value:
                malformed = True
                continue
            if key in _MONEY_FIELDS:
                amount = _parse_decimal(value)
                if amount is None:
                    malformed = True
                    continue
                parsed[key] = amount
            else:
                parsed[key] = value

        if spec.intent is Intent.SECURITY_REVIEW and "transaction_id" not in parsed:
            parsed["transaction_id"] = None
        missing = [field for field in spec.required if field not in parsed]
        if missing or malformed:
            if missing:
                question = f"נא לספק את הפרמטרים החסרים: {', '.join(missing)}."
            else:
                question = "נא לתקן את מבנה הפרמטרים של הפקודה."
            return _clarification(spec.intent, parsed, question)
        return RouterDecision(
            intent=spec.intent,
            parameters=parsed,
            confidence=1.0,
        )

    async def route(self, user_input: str) -> AgentResult:
        """Parse one supported command without executing any operation."""

        if not isinstance(user_input, str):
            raise TypeError("user_input must be a string")
        text = user_input.strip()
        natural = self._natural_transfer(text)
        if natural is not None:
            mode = "natural" if natural.confidence == 0.90 else "clarification"
            return self._result(natural, mode)
        canonical = self._canonical(text)
        if canonical is not None:
            mode = "canonical" if canonical.confidence == 1.0 else "clarification"
            return self._result(canonical, mode)
        if re.match(r"^(?:transfer\b|העבר\b)", text, flags=re.IGNORECASE):
            decision = _clarification(
                Intent.TRANSFER_MONEY,
                {},
                "נא לספק סכום, שולח ומקבל במבנה הנתמך.",
            )
            return self._result(decision, "clarification")
        return self._result(self._unknown(), "unknown")

    async def run(self, context: AgentContext) -> AgentResult:
        """Route the immutable context input."""

        if not isinstance(context, AgentContext):
            raise TypeError("context must be AgentContext")
        return await self.route(context.user_input)
