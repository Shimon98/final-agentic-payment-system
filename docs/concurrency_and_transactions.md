# Concurrency and Transaction Safety

## Problems being controlled

A race condition occurs when correctness depends on task interleaving. A lost update occurs when
two tasks read the same old value and the later write erases the earlier write. Double spending
is the debit form of that problem: two withdrawals independently accept the same funds. A
deadlock occurs when tasks hold resources while waiting for each other in opposite order.

For example, two concurrent debits of 80 from a balance of 100 must not both validate against
100. The service locks the wallet before the read-check-write sequence, so one succeeds and the
other observes the new balance.

## Resource identity and ordering

`LockKey` combines a `LockScope` and resource ID. The exact scope order is:

| Scope | Numeric value |
|---|---:|
| `IDEMPOTENCY` | 10 |
| `USER_REGISTRY` | 20 |
| `PAYMENT_REQUEST` | 30 |
| `TRANSACTION` | 40 |
| `WALLET` | 50 |

`AsyncResourceLockManager.acquire_many()` removes duplicate keys, sorts by `(scope,
resource_id)`, obtains lock objects safely, acquires in sorted order, and releases in reverse
order. Opposite-direction transfers therefore request the two wallet locks in the same global
order rather than sender-first order.

## Lock scopes and business resources

- `IDEMPOTENCY` serializes one retry identity.
- `USER_REGISTRY` protects the shared user/phone registry.
- `PAYMENT_REQUEST` protects one request transition.
- `TRANSACTION` protects one risk annotation.
- `WALLET` protects balance validation and replacement.

An operation acquires its complete conflict set and re-reads the latest state inside the critical
section. No slow model call, SDK handoff, network operation, arbitrary sleep, or user interaction
is allowed while financial locks are held.

## Global JSON transaction gate

Resource locks allow unrelated business work to proceed until commit. Because the JSON
implementation stores one aggregate file, `PaymentTransactionManager` also has one transaction
gate. It serializes creation of a working clone, persistence, and publication of the next shared
state so two commits cannot replace each other with stale aggregates.

This deliberately trades JSON write concurrency for correctness.

## Copy-on-write Unit of Work

`PaymentUnitOfWork` owns a clone of the committed `ApplicationState`. The service mutates only
that private working aggregate, appends audit events to its outbox dictionary, validates all
invariants, and calls `commit()` once. The transaction manager persists the complete clone before
publishing it as current state.

If validation, persistence, or the surrounding operation fails before commit, `rollback()` marks
the unit closed and the shared state is unchanged. Rollback is safe when repeated.

## Atomic commit and persistence

State serialization completes before writing. The repository writes one temporary file, flushes
it, calls `fsync`, and atomically replaces the target. The in-memory aggregate is published only
after that save succeeds. Readers therefore do not observe a partially committed aggregate.

## Cancellation safety

Lock acquisition tracks the locks actually obtained. A `finally` block releases those locks in
reverse order on success, ordinary failure, or cancellation. Cancellation is re-raised. Threaded
filesystem work is shielded so cancellation cannot make memory claim a disk write was absent
when it actually completed.

## Idempotency

Every mutation uses a stable idempotency key and canonical request fingerprint. The key's lock is
part of the operation lock set.

- Same key and same fingerprint: reconstruct or return the original result.
- Same key and different fingerprint: reject with an idempotency conflict.
- Record, result references, optional result payload, business state, and audit event commit
  together.

## Why locks and idempotency are both required

Locks protect simultaneous operations that contend for current state, even when they have
different request identities. Idempotency protects repeated delivery of the same logical
request, including retries that occur after the first lock has long been released. Locks alone
would allow a later retry to create a second transaction; idempotency alone would not prevent two
different debit requests from overspending one wallet.

## Scope limitation

These locks, the transaction gate, and in-memory indexes protect one Python process and one event
loop. They are not cross-process or distributed locks. Production multi-process or distributed
use requires a transactional database, database-level isolation or row locking, durable
constraints, and production recovery procedures.
