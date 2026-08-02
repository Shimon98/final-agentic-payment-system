# Prompt Documentation

The single implementation source is
[`src/agentic_payments/agents/prompts.py`](../src/agentic_payments/agents/prompts.py). This
document explains those constants; it does not define alternative prompt text.

## Shared boundaries

Every system prompt identifies the project as an educational simulation, forbids real financial
connections and direct balance changes, makes deterministic tools authoritative, requires the
supplied structured schema, and forbids invented information. Optional SDK definitions add
read-only triage and specialist restrictions.

| Constant | Agent | Purpose and output boundary |
|---|---|---|
| `ROUTER_SYSTEM_PROMPT` | `RouterAgent` / SDK router | Select an approved intent and extract only supplied parameters as `RouterDecision`; never execute it |
| `FRAUD_SYSTEM_PROMPT` | `FraudDetectionAgent` / fraud specialist | Explain supplied deterministic score, level, and reasons; never replace the score |
| `SECURITY_SYSTEM_PROMPT` | `SecurityAgent` / security specialist | Review only immutable transaction or application-state facts as structured review |
| `EXPLANATION_SYSTEM_PROMPT` | `ExplanationAgent` / explanation specialist | Phrase stored facts and acknowledge missing facts; never invent financial details |
| `CRITIC_SYSTEM_PROMPT` | `CriticAgent` | Review `AgentResult` completeness without retrying an operation |
| `REFLECTION_SYSTEM_PROMPT` | `ReflectionAgent` | Explain a supplied error and propose non-executing recovery guidance |
| `FALLBACK_SYSTEM_PROMPT` | `FallbackAgent` | Ask for missing information or list supported operations without mutation |

## Structured output

The router uses `RouterDecision`. Read-only SDK specialists use
`ReadOnlySpecialistOutput`. Local Pydantic validation rejects extra fields, invalid confidence,
unsupported intent, inconsistent flags, or malformed content before orchestration uses the
result.

## Read-only specialist restrictions

The SDK triage agent can hand off only to fraud, security, or explanation specialists. Each
specialist has one authorized read-only fact tool:

- `get_fraud_review_facts`;
- `get_security_review_facts`;
- `get_last_action_facts`.

Handoffs receive filtered JSON-compatible facts, not mutable repositories. No prompt or SDK tool
is authorized to transfer funds, create users, approve requests, modify state files, or bypass
policy.

## Operational rule

Prompts are advisory boundaries in addition to, not instead of, typed commands, local schemas,
guardrails, deterministic policies, locks, idempotency, and Unit of Work validation. The project
runs with the deterministic prompt-free route when model routing is disabled.
