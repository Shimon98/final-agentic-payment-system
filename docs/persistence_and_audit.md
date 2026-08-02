# Persistence, Audit, and Idempotency

## Application state

`ApplicationState` is the local source-of-truth aggregate. It contains users, wallets,
transactions, payment requests, state-backed idempotency records, pending audit events, and
business memory.

All keyed collections are serialized deterministically in sorted-key order. Monetary `Decimal`
values are JSON strings so binary floating-point conversion cannot change money. Datetimes are
timezone-aware ISO 8601 strings. Deserialization rejects unknown fields, malformed values,
unsupported relationships, duplicate logical data, and outbox key/event-ID mismatches.

## Atomic JSON replacement

`JsonStateRepository.save_atomic()` validates and serializes the complete state before disk
mutation. Its synchronous write path:

1. creates the parent directory only when a write is requested;
2. writes the complete payload to a same-directory temporary file;
3. flushes the file;
4. calls `fsync`;
5. uses atomic replacement for the target;
6. cleans a remaining temporary file after failure.

Filesystem work runs in a thread behind a repository lock. A malformed existing state is reported
as a safe persistence error and is not silently erased.

## JSONL audit log

`JsonLinesAuditRepository` stores one complete UTF-8 JSON object and newline per `AuditEvent`.
Initialization builds an event-ID index. Blank lines are ignored, malformed nonblank lines are
rejected, identical repeated event IDs represent one logical event, and conflicting content for
the same ID is rejected.

Audit details contain structured simulation metadata, not provider credentials or raw
environment values. JSONL is an audit record, not a state-replay implementation.

## Transactional pending outbox

`pending_audit_events` is a dictionary whose key must equal `AuditEvent.event_id`. The domain
operation places the event in the same working state as its business mutation. Atomic JSON commit
therefore makes the business result and pending delivery durable together.

`AuditOutboxDispatcher.flush_pending()` processes a deterministic snapshot of sorted event IDs:

1. check whether the audit repository already contains the event ID;
2. append the event when absent;
3. treat an identical prior event as idempotently delivered;
4. remove the pending entry in a new atomic state transaction;
5. report per-event failures and the remaining count.

An event is never removed merely because delivery was attempted.

## Delivery confirmation and crash window

There is a deliberate cross-file crash window: the JSONL append can finish before persistence of
the outbox removal. After restart, state still lists that event as pending. The dispatcher checks
the JSONL index, confirms the identical event already exists, and removes the pending entry
without appending a duplicate logical event.

If event-ID content conflicts, delivery fails safely and the pending event remains available for
diagnosis and retry.

## Restart

`build_application()` initializes the audit index, loads and validates state, composes the
application, then flushes pending audit events before normal handling. Users, wallet versions,
transactions, request statuses, idempotency records, and `BusinessMemory` survive reconstruction
from the same paths.

## State-backed idempotency

`IdempotencyRecord` stores the key, operation type, canonical SHA-256 request fingerprint, result
reference, creation time, and optional serialized result payload. It is part of the same state
commit as the mutation. Retries can reconstruct exact results, including operations whose result
requires more than one referenced entity.

## Safe reset

`ApplicationContainer.reset_state()` first flushes pending audit delivery. It refuses to discard
state while delivery remains pending, then commits an empty aggregate through one Unit of Work.
The CLI requires explicit `reset --yes` confirmation for non-interactive reset and uses a
confirmation prompt interactively. Reset is intended for local simulation data.

## Guarantee boundary

Atomic replacement covers one state file and the locks cover one process and event loop. JSON and
JSONL are not a distributed transaction. Multi-process production storage requires a
transactional database and database-backed audit/outbox strategy.
