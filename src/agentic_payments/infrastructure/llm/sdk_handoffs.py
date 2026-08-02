"""Sanitizing public SDK handoff definitions for read-only specialists."""

from __future__ import annotations

import json

from agents import Agent, Handoff, HandoffInputData, handoff

from agentic_payments.infrastructure.llm.context import (
    SDKReadOnlyContext,
    json_compatible_copy,
)


def _sanitize_handoff_input(data: HandoffInputData) -> HandoffInputData:
    context_wrapper = data.run_context
    if context_wrapper is None or not isinstance(context_wrapper.context, SDKReadOnlyContext):
        sanitized = json.dumps(
            {"task": "invalid_read_only_context"},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    else:
        context = context_wrapper.context
        sanitized = json.dumps(
            {
                "task": context.allowed_intent.value,
                "correlation_id": context.correlation_id,
                "requested_at": context.requested_at.isoformat(),
                "facts": json_compatible_copy(context.facts),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    return data.clone(
        input_history=sanitized,
        pre_handoff_items=(),
        new_items=(),
        input_items=(),
    )


def _read_only_handoff(
    target: Agent[SDKReadOnlyContext],
) -> Handoff[SDKReadOnlyContext, Agent[SDKReadOnlyContext]]:
    return handoff(
        target,
        input_filter=_sanitize_handoff_input,
        nest_handoff_history=False,
    )
