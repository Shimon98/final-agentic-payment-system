"""Safe deterministic fallback responses that never execute operations."""

from __future__ import annotations

from agentic_payments.agents.base import AgentContext, BaseAgent
from agentic_payments.application import AgentResult, RouterDecision

_SUPPORTED_INTENTS = [
    "createUser",
    "checkBalance",
    "transferMoney",
    "requestPayment",
    "approvePayment",
    "rejectPayment",
    "showTransactions",
    "fraudCheck",
    "securityReview",
    "explainLastAction",
]

_DEFAULT_QUESTION = "איזה מידע חסר תרצה לספק כדי להמשיך בבטחה?"


def _output(
    *,
    reason: str,
    message_he: str,
    message_en: str,
    clarification_question: str | None,
) -> dict[str, object]:
    return {
        "reason": reason,
        "message_he": message_he,
        "message_en": message_en,
        "clarification_question": clarification_question,
        "supported_intents": list(_SUPPORTED_INTENTS),
    }


class FallbackAgent(BaseAgent):
    """Ask for safe clarification without fabricating or executing parameters."""

    @property
    def name(self) -> str:
        """Return the stable fallback-agent identity."""

        return "FallbackAgent"

    async def handle_unknown(self, user_input: str) -> AgentResult:
        """Return supported operations without echoing the unknown request."""

        if not isinstance(user_input, str):
            raise TypeError("user_input must be a string")
        return AgentResult(
            self.name,
            _output(
                reason="unknown_intent",
                message_he="לא ניתן לזהות פעולה נתמכת בבטחה.",
                message_en="A supported operation could not be identified safely.",
                clarification_question="איזו פעולה נתמכת ברצונך לבצע?",
            ),
            1.0,
        )

    async def handle_low_confidence(self, decision: RouterDecision) -> AgentResult:
        """Request clarification for a decision below the fixed safety threshold."""

        if not isinstance(decision, RouterDecision):
            raise TypeError("decision must be RouterDecision")
        if decision.confidence >= 0.80:
            raise ValueError("low-confidence fallback requires confidence below 0.80")
        question = decision.clarification_question or _DEFAULT_QUESTION
        return AgentResult(
            self.name,
            _output(
                reason="low_confidence",
                message_he="רמת הביטחון בזיהוי הבקשה נמוכה מדי לביצוע.",
                message_en="Routing confidence is too low to continue.",
                clarification_question=question,
            ),
            1.0,
        )

    async def request_missing_parameters(self, decision: RouterDecision) -> AgentResult:
        """Ask only for missing information identified by the router."""

        if not isinstance(decision, RouterDecision):
            raise TypeError("decision must be RouterDecision")
        if not decision.requires_clarification:
            raise ValueError("missing-parameters fallback requires clarification")
        question = decision.clarification_question or _DEFAULT_QUESTION
        return AgentResult(
            self.name,
            _output(
                reason="missing_parameters",
                message_he="חסר מידע הנדרש להמשך בטוח.",
                message_en="Required information is missing for safe continuation.",
                clarification_question=question,
            ),
            1.0,
        )

    async def run(self, context: AgentContext) -> AgentResult:
        """Dispatch one explicitly selected fallback mode."""

        if not isinstance(context, AgentContext):
            raise TypeError("context must be AgentContext")
        mode = context.payload.get("fallback_mode")
        if mode == "unknown":
            return await self.handle_unknown(context.user_input)
        if mode == "low_confidence":
            if context.router_decision is None:
                raise ValueError("low_confidence requires router_decision")
            return await self.handle_low_confidence(context.router_decision)
        if mode == "missing_parameters":
            if context.router_decision is None:
                raise ValueError("missing_parameters requires router_decision")
            return await self.request_missing_parameters(context.router_decision)
        raise ValueError("fallback_mode must be unknown, low_confidence, or missing_parameters")
