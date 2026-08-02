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

The builder discovers all production Python files, sorts normalized relative paths, records a
SHA-256 manifest, writes readable `%%writefile` cells, executes in a fresh kernel, preserves
outputs, and atomically replaces the final artifact only after success.

## Validate

```powershell
uv run python scripts/validate_notebook.py
```

Validation checks nbformat, section order, all embedded sources and hashes, execution counts,
required scenario output, privacy, repository data isolation, and portability.

The expected final success text includes:

```text
10/10 lecturer scenarios passed
FINAL NOTEBOOK VALIDATION PASSED
Temporary notebook runtime cleaned successfully.
```

## Run

Open the root notebook in a Python 3 Jupyter environment and run all cells from a clean kernel.
No API key is required. The notebook uses rule-based mode and does not make a provider request.

## Portability

The notebook contains all current production source as readable cells. Its first executable setup
creates a `TemporaryDirectory`, changes into it, writes the embedded package below temporary
`src/`, and uses temporary state and audit files. The final cell cleans that runtime.

The validator copies only the notebook into an otherwise empty temporary directory and executes
the copy. No repository source file is needed during that isolated run.

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

## Source-manifest synchronization

`scripts/validate_notebook.py` compares every current production path, SHA-256 value, and exact
embedded source cell. Any production change requires rebuilding before validation can pass.

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
