# Agent Flows

Every flow starts with a typed, validated boundary. State-changing intents proceed only after
deterministic routing confidence and required-parameter checks.

## 1. Create user

`createUser` → `CreateUserCommand` → input guardrail → facade → locked
`PaymentDomainService.create_user` → user and wallet in one Unit of Work → memory → output
guardrail → critic → outbox. The phone registry and idempotency resources are locked together.

## 2. Check balance

`checkBalance` → `CheckBalanceCommand` → guardrail → facade → deterministic wallet read → safe
result → memory → critic. The read does not create a financial mutation.

## 3. Transfer money

```text
Route
  -> typed command
  -> input guardrail
  -> facade
  -> policy advisory
  -> locked domain mutation
  -> snapshot
  -> fraud
  -> risk annotation
  -> optional security
  -> output guardrail
  -> critic
  -> memory
  -> outbox
```

The domain service re-reads balances while both wallet locks and the idempotency lock are held.
It commits both immutable wallet replacements, the transaction, idempotency record, and pending
audit event atomically. Fraud scoring runs from the returned immutable snapshot after those locks
are released. Risk annotation is a separate idempotent mutation.

## 4. Request payment

`requestPayment` → typed requester, payer, and amount → participant and policy validation →
locked request creation → memory → critic → outbox. No funds move while a request is pending.

## 5. Approve payment

The request is first read to discover participants, then re-read after acquiring the exact
request, wallet, and idempotency locks. Approval, payer debit, requester credit, generated
transaction, idempotency record, and audit event commit together. Fraud and optional security
post-processing follow the same snapshot path as a direct transfer.

## 6. Reject payment

`rejectPayment` → typed request ID → request and idempotency locks → pending-status check →
immutable rejected request → one commit → memory, critic, and outbox.

## 7. Fraud check

`fraudCheck` selects an existing transaction, builds immutable facts, and runs
`FraudDetectionAgent`. Explicit checks are read-only; the transfer flow alone persists its
authoritative risk annotation.

## 8. Security review

`securityReview` either reviews a selected transaction snapshot or a cloned application state.
The agent checks references, balances, arithmetic, and consistency without altering them.

## 9. Explain last action

`explainLastAction` reads the persisted `BusinessMemory` snapshot and stored referenced facts.
`ExplanationAgent` produces deterministic text when the optional specialist is unavailable. It
does not invent missing IDs, amounts, balances, statuses, or reasons.

## 10. Unknown intent

`unknown` never maps to a payment tool. `FallbackAgent.handle_unknown` returns supported-operation
guidance, the result is criticized, and financial state remains unchanged.

## 11. Low-confidence routing

When confidence is below the execution threshold or clarification is required,
`FallbackAgent.handle_low_confidence` or `request_missing_parameters` asks for safer input. No
typed mutating command is dispatched.

## 12. Domain error and ReflectionAgent

Typed domain errors such as invalid amount, insufficient funds, self-transfer, resolved request,
or policy violation are given to `ReflectionAgent.reflect_on_error`. The response contains an
error code, user-facing explanation, recovery steps, and optional suggested parameters. Advice
does not retry or mutate.

## 13. Post-commit warning behavior

A committed financial mutation is never hidden by a later guardrail or critic failure. If
post-processing, memory persistence, or outbox delivery fails after commit, the orchestrator
returns the committed result with safe warning metadata. It does not report that the mutation
failed and does not retry with a new idempotency key.

## 14. Read-only SDK specialist handoff

Only `fraudCheck`, `securityReview`, and `explainLastAction` can enter the specialist route.
Application code supplies an `SDKReadOnlyContext`; the handoff filter discards conversation
history and forwards a sanitized task and immutable facts. Triage hands off once to the matching
specialist, which may call only its authorized fact reader. Structured output is validated
locally before it is accepted. State-changing intents remain in the deterministic tool path.
