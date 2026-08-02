# Security

## Educational threat model

The project assumes a local educational operator and untrusted natural-language requests. It
protects simulation integrity from malformed commands, unclear routing, duplicate retries,
concurrent local mutations, malformed persisted data, unsafe model output, and accidental secret
display. It does not treat the local machine, filesystem owner, or configured provider as
hostile.

## Trust boundaries

- User text is untrusted until routing, command construction, and input guardrails pass.
- Optional model output is untrusted until schema and output guardrails pass.
- Persisted JSON and JSONL are untrusted on load and are validated.
- Domain entities and immutable snapshots are trusted only after their invariants pass.
- Presentation output is filtered before display.

## Deterministic financial mutation

No agent, prompt, or SDK tool changes a balance. Only `PaymentDomainService`, through ordered
resource locks, `PaymentTransactionManager`, and `PaymentUnitOfWork`, may commit business state.
`Decimal`, explicit policies, idempotency fingerprints, and aggregate invariants remain
authoritative regardless of model output.

## SDK tools, guardrails, and handoffs

The SDK exposes only three fact readers for fraud, security, and last-action explanation. Tool
input guardrails require the exact authorized intent and tool name. Tool output guardrails
validate JSON-compatible, size-bounded, secret-free facts.

The handoff filter discards prior conversation items and forwards a sanitized task, correlation
ID, aware request time, and immutable facts. Triage can hand off only to the matching read-only
specialist. State-changing intents cannot enter this path.

Application `ToolGuardrails` also enforce exact command types, routing confidence, required
parameters, and intent-specific result shapes. A later guardrail or critic failure cannot conceal
an already committed financial result.

## Secrets and local configuration

Ordinary execution and CI use `rule_based` mode and need no provider credential. Optional
credentials belong only in the ignored local `.env` file. `.env.example` contains names and blank
placeholders. Secrets must not appear in source, tests, documentation, notebook cells or outputs,
audit details, logs, command history, or CI configuration. `Settings` stores a configured
credential as `SecretStr`.

## Privacy and safe output

Presentation formatters mask phone numbers and serialize only supported safe values. Public
examples use fictional identifiers and omit complete phone numbers. Infrastructure and CLI
boundaries expose generic safe failure messages rather than internal exception details.
Correlation IDs support diagnosis without disclosing credentials.

Agent metadata is restricted to expected routing, critic, warning, and specialist fields.
Read-only SDK facts are copied to JSON-compatible structures and bounded before use.

## Audit limitations

The JSONL audit log records simulation actions and correlations but is not tamper-evident,
encrypted, access-controlled, remotely replicated, or sufficient for regulatory audit. It is
local educational evidence. A real system would require protected centralized logging,
retention policy, monitoring, and incident response.

## Authentication and authorization

The CLI has no production identity verification, session management, role model, ownership
authorization, or privileged administration boundary. User IDs in commands are simulation
identifiers, not authenticated principals.

## What this project does not provide

- PCI DSS or banking compliance.
- Production fraud prevention or financial risk decisions.
- Production-grade authentication or authorization.
- Real bank, card, wallet-provider, or payment-processor integration.
- Secure key management, encrypted storage, or regulated audit retention.
- Cross-process, cross-host, or distributed locking.
- A production incident-response or availability architecture.

`asyncio` locks and the JSON transaction gate protect one Python process and one event loop.
Production deployment requires a transactional database, database-level concurrency controls,
real identity and authorization, secret management, monitoring, backups, and independent
security review.
