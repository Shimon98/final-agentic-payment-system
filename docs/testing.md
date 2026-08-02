# Testing

## Test layers

### Unit tests

Unit tests validate entities, serialization, policy, command and schema validation, memory,
routing, every specialist agent, tool guardrails, SDK definitions, settings, IDs, clocks, and
notebook construction. Fixed aware datetimes and deterministic fakes keep expected values stable.

### Integration tests

Integration tests compose repositories, transaction management, domain services, facade,
orchestrator, outbox, CLI, optional SDK boundaries, and notebook validation. Filesystem tests use
temporary directories and simulate write, replacement, and audit failures.

### Concurrency tests

Concurrency tests cover:

- double-spending prevention;
- concurrent credits without lost updates;
- opposite-direction transfers without deadlock;
- concurrent idempotent retries;
- duplicate payment-request approval;
- JSON and JSONL serialization;
- outbox serialization;
- cancellation during lock and filesystem work.

Every bounded concurrency scenario uses an explicit timeout rather than an arbitrary long sleep.

### End-to-end tests

End-to-end tests exercise the CLI entry points, the ten required lecturer scenarios, restart,
concurrency demonstrations, and the final submission notebook as a user-observable system.

### Notebook tests

Notebook tests verify deterministic source discovery and hashes, readable embedded source,
stable cell IDs, exact root filename, required Hebrew RTL sections, executed outputs, all scenario
PASS lines, privacy, atomic replacement, source-manifest synchronization, and execution after the
notebook is copied alone into an empty directory.

### Optional live LLM tests

Files under `tests/live` are marked `live_llm`, require
`RUN_LIVE_LLM_TESTS=true`, and are opt-in. Standard tests and CI exclude them. They are not needed
to validate deterministic business behavior.

## Determinism and isolation

Business tests inject fixed UTC clocks and deterministic ID generators where exact values matter.
No unit, integration, concurrency, end-to-end, or notebook test requires a provider request.
Persistence uses pytest temporary directories or notebook-owned `TemporaryDirectory` paths, so
repository `data/` remains only the placeholder.

## Historical Phase 10 validation

The approved Phase 10 validation result was:

- Phase 1–10 regression: **944 passed**.
- Combined coverage: **88.00%**.

These are historical Phase 10 results, not a permanent guarantee. Adding tests or changing source
changes totals. Phase 12 will run and report final totals again.

## Standard commands

```powershell
uv run pytest tests/unit tests/integration tests/concurrency tests/end_to_end -m "not live_llm"
```

Coverage gate:

```powershell
uv run pytest tests/unit tests/integration tests/concurrency tests/end_to_end -m "not live_llm" --cov=src/agentic_payments --cov=scripts --cov-report=term-missing --cov-fail-under=85
```

Quality:

```powershell
uv run ruff check src scripts tests
uv run ruff format --check src scripts tests
uv run mypy src/agentic_payments scripts
```

Notebook validation:

```powershell
uv run python scripts/validate_notebook.py
```

CI repeats the deterministic suite with frozen dependencies, Python 3.12, rule-based routing, and
no provider secrets.
