# Submission Instructions

## Exact artifact

The submission notebook is exactly:

```text
final_agentic_payment_project.ipynb
```

It lives at the repository root. Do not create a second submission notebook.

## Rebuild

From the repository root:

```powershell
uv sync
uv run python scripts/build_notebook.py
```

The builder creates a concise lecturer-facing demonstration, imports the production package from
the repository `src/` directory, executes in a fresh kernel from the repository root, preserves
outputs, and atomically replaces the final artifact only after success.

## Validate

```powershell
uv run python scripts/validate_notebook.py
```

Validation checks nbformat, section order, repository-based imports, execution counts, required
scenario output, privacy, temporary-data isolation, readability limits, and the clear error shown
when repository source is absent.

The expected final success text includes:

```text
10/10 lecturer scenarios passed
FINAL NOTEBOOK VALIDATION PASSED
Temporary notebook runtime cleaned successfully.
```

## Run

Open the root notebook in a Python 3 Jupyter environment and run all cells from a clean kernel.
No API key is required. The notebook uses rule-based mode and does not make a provider request.

## Repository-based execution

The complete repository is submitted. `src/` contains the full implementation and is the
one source of truth; the notebook is the executable demonstration and does not duplicate production
implementation. Run it from the repository root. Its setup imports `src/agentic_payments`, creates
a `TemporaryDirectory`, and uses only temporary state and audit files. The final cell cleans that
runtime.

The validator executes the notebook from the repository root and separately confirms that a copy
run without `src/agentic_payments` fails with a clear instruction instead of reconstructing the
project.

## Demonstrated behavior

The executed notebook includes:

1. creation of two users and balance checks;
2. successful transfer;
3. negative transfer amount;
4. insufficient funds;
5. nonexistent receiver;
6. self-transfer;
7. payment-request creation and approval;
8. repeated approval with a different idempotency key;
9. high-risk suspicious transaction detection and security review;
10. explanation of the last action from persisted business memory.

It also demonstrates PolicyAgent, ReflectionAgent, JSON restart, audit outbox delivery, three
concurrency scenarios, and optional SDK structure without a live request.

## Source synchronization

The notebook imports current production code directly from `src/`; it contains no embedded
production-source copy and no source manifest. Rebuild and validate the notebook after production
changes so the saved demonstrations reflect the current implementation.

## Repository inclusion list

Include:

- `src/`
- `tests/`
- `scripts/`
- `docs/`
- `final_agentic_payment_project.ipynb`
- `README.md`
- `pyproject.toml`
- `uv.lock`
- `.env.example`
- `.github/workflows/ci.yml`
- `LICENSE`

## Exclusion list

Exclude:

- `.env`
- `.codex-local`
- `.idea`
- `.venv`
- caches
- temporary data
- API keys
- live provider outputs

Repository `data/` should contain only `.gitkeep`. Do not include local JSON state, JSONL audit
records, notebook checkpoints, coverage databases, or IDE configuration.
