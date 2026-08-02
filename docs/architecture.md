# Architecture

## Goals

The architecture keeps financial decisions deterministic while allowing agents to classify,
review, explain, and suggest. Its main goals are:

- a domain independent of filesystems and model providers;
- typed application boundaries;
- one authoritative financial mutation service;
- atomic local persistence with retryable audit delivery;
- safe execution without a provider credential;
- explicit single-process concurrency guarantees and limitations.

## Dependency direction and packages

```text
presentation
    -> application
        -> domain

infrastructure -> application ports and domain types
agents         -> application contracts and immutable domain facts
tools          -> application facade
bootstrap      -> composes every layer
```

| Package | Responsibility |
|---|---|
| `domain` | Immutable entities, enums, snapshots, exceptions, and transfer policy |
| `application` | Commands, results, aggregate state, memory, orchestration, facade, services, ports |
| `agents` | Routing, review, explanation, policy advice, reflection, and fallback |
| `tools` | Static intent-to-facade dispatch and input/output guardrails |
| `infrastructure` | Locks, transactions, JSON/JSONL persistence, outbox, IDs, clock, optional SDK |
| `presentation` | CLI parsing, interaction, demonstration, and safe formatting |

## Major command path

```text
User
  -> RouterAgent / HybridRouterAgent
  -> OrchestratorAgent
  -> ToolGuardrails
  -> PaymentToolRegistry
  -> PaymentFacade
  -> PaymentDomainService
  -> AsyncResourceLockManager
  -> PaymentTransactionManager
  -> PaymentUnitOfWork
  -> JsonStateRepository
```

`OrchestratorAgent.handle()` creates or accepts correlation, idempotency, and aware request-time
values. It validates the routing result, constructs the exact immutable command, runs the input
guardrail, and dispatches through the static tool registry. Repositories implement storage
mechanics; they do not decide whether a transfer or request is valid.

## Deterministic and LLM boundaries

Agents can classify intent, extract explicitly supplied parameters, score or review immutable
facts, explain stored facts, criticize result quality, and suggest safe recovery. Agents do not
change balances. `PaymentDomainService` is the mutation boundary and all balance changes pass
through its policy, lock, Unit of Work, invariant, idempotency, and commit path.

`HybridRouterAgent` may consult `OpenAIAgentsRuntime` only when explicitly configured. Invalid or
unavailable model routing falls back to `RouterAgent`. Optional specialist handoffs are read-only
and limited to fraud, security, and last-action explanation facts. There is no financial SDK
function tool.

## Post-processing path

```text
TransactionSnapshot
  -> FraudDetectionAgent
  -> idempotent risk annotation
  -> SecurityAgent when required
  -> output guardrail
  -> CriticAgent
  -> BusinessMemory
  -> AuditOutboxDispatcher
```

Fraud and security work occurs outside the original transfer locks. Risk annotation is a separate
idempotent domain mutation. A committed financial result is retained even when later review,
guardrail, critic, memory persistence, or outbox delivery produces a safe warning.

## Read-only specialist path

```text
Explicit read-only intent
  -> Orchestrator gathers immutable facts
  -> SDKReadOnlyContext
  -> filtered triage handoff
  -> one authorized read-only fact tool
  -> locally validated ReadOnlySpecialistOutput
  -> deterministic application result remains authoritative
```

Handoff history is replaced with a sanitized task, correlation ID, aware request time, and
JSON-compatible fact copy. Tools reject mismatched intents and unexpected fact shapes.

## Persistence and outbox paths

Application state is one aggregate in the JSON implementation:

```text
working clone
  -> invariant validation
  -> serialize complete aggregate
  -> temporary file
  -> flush + fsync
  -> atomic replace
  -> publish committed in-memory state
```

The same working state contains `pending_audit_events`, keyed by immutable event ID. After state
commit:

```text
pending event
  -> check JSONL event index
  -> append complete line or recognize identical prior delivery
  -> persist state without the delivered event
```

If JSONL delivery succeeds but pending-event removal cannot be persisted, a restart retries the
event. The JSONL repository recognizes an identical event ID and avoids a duplicate logical
event.

## Restart path

`build_application()` validates settings, initializes the audit repository, loads and validates
JSON state, constructs every service, creates the rule-based or optional hybrid router, and
flushes pending audit events before returning the `ApplicationContainer`. Safe startup warnings
report delivery problems without erasing committed state.

## Error-handling path

Typed domain failures are converted by `ReflectionAgent` into non-mutating recovery advice.
Unknown intent, low confidence, or missing parameters go to `FallbackAgent`. Infrastructure and
unexpected errors become generic presentation-safe failures. Cancellation is propagated and
acquired locks are released in `finally` blocks.

## Concurrency boundary

Resource locks protect business conflicts; a global transaction gate protects replacement of the
single JSON aggregate. These guarantees cover one Python process and one event loop only.
Multi-process or distributed operation requires a transactional database, database isolation or
row locks, and production operational controls.
