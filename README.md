# Agentic Payment System

Production-inspired educational payment simulation using deterministic business logic and
guarded AI agents.

## Educational disclaimer

This repository is an educational simulation only. It has no real bank, card, or
payment-provider integration, and no real financial data should be used with it. Financial
mutations are deterministic. Language-model behavior is optional and advisory.

## Overview

The project demonstrates how a typed Python application can combine intent routing and
specialist agents with deterministic payment rules. A router classifies a request, an
orchestrator constructs a validated command, guarded tools dispatch it, and
`PaymentDomainService` is the only financial mutation boundary. The default `rule_based` mode
runs the complete ordinary workflow without an API key or network provider.

להסברים קצרים בעברית ולכל תרחישי ההדגמה, ראו את
[מחברת ההגשה](final_agentic_payment_project.ipynb).

## Key capabilities

- User and immutable, versioned wallet creation.
- Balance reads, transfers, payment requests, approvals, rejections, and history.
- Deterministic fraud scoring, policy checks, security review, criticism, reflection, and
  fallback.
- Typed commands and a shared `AgentResult` contract.
- Business memory, persisted idempotency records, and a transactional audit outbox.
- Atomic JSON state replacement and idempotent JSONL audit delivery.
- Deterministically ordered asynchronous locks with cancellation-safe release.
- Optional guarded OpenAI Agents SDK routing and read-only specialist handoffs.
- A repository-based, executed submission notebook that imports the production package from
  `src/`.

## Architecture

Dependency direction is presentation → application → domain, with infrastructure implementing
application ports. Agents may classify, review, and explain; they never change balances.

```text
User
  -> RouterAgent / HybridRouterAgent
  -> OrchestratorAgent
  -> ToolGuardrails
  -> PaymentToolRegistry
  -> PaymentFacade
  -> PaymentDomainService
  -> Locks + Unit of Work + JSON state
  -> Fraud / Security / Critic / Memory / Audit Outbox
```

See [Architecture](docs/architecture.md) for command, persistence, restart, error, and optional
SDK paths.

## Agent responsibilities

| Agent | Responsibility | Direct financial mutation |
|---|---|---|
| `RouterAgent` | Deterministic intent classification and parameter extraction | No |
| `HybridRouterAgent` | Optional LLM routing with deterministic fallback | No |
| `FraudDetectionAgent` | Deterministic post-transfer risk scoring | No |
| `SecurityAgent` | Read-only transaction or state review | No |
| `ExplanationAgent` | Explanation from stored transaction and memory facts | No |
| `CriticAgent` | Final-result quality review | No |
| `PolicyAgent` | Advisory transfer-policy evaluation before mutation | No |
| `ReflectionAgent` | Safe recovery guidance after typed failures | No |
| `FallbackAgent` | Clarification or supported-operation guidance | No |

Detailed responsibilities and methods are in
[Class design](docs/class_design.md) and [Agent flows](docs/agent_flows.md).

## Supported intents

| Intent value | Operation |
|---|---|
| `createUser` | Create a user and wallet |
| `checkBalance` | Read a wallet balance |
| `transferMoney` | Transfer funds |
| `requestPayment` | Create a payment request |
| `approvePayment` | Approve a pending request and transfer funds |
| `rejectPayment` | Reject a pending request |
| `showTransactions` | List a user's transactions |
| `fraudCheck` | Review one stored transaction |
| `securityReview` | Review one transaction or the whole state |
| `explainLastAction` | Explain the newest remembered action |
| `unknown` | Return a non-mutating fallback |

## Payment business rules

- Monetary values use finite `Decimal` values with at most two fractional digits.
- Initial balances are non-negative; transfer and request amounts are positive.
- Users, wallets, transactions, and payment requests must reference existing owners.
- A user cannot transfer to themselves or request payment from themselves.
- A debit cannot create a negative balance.
- The configured single-transfer and daily-transfer limits are enforced.
- A payment request can be resolved only once.
- Every mutation requires an idempotency key.
- The same key and request fingerprint returns the original result; a different fingerprint
  raises a conflict.
- Wallets are immutable and increment their version on every balance change.

## Concurrency and transaction safety

Resource locks prevent conflicting read-check-write sequences from interleaving. Locks are
deduplicated, sorted by `LockScope` and resource ID, acquired in that order, and released in
reverse. A copy-on-write Unit of Work validates the complete aggregate before one atomic commit.
A separate JSON transaction gate serializes state-file replacement.

These guarantees apply to one Python process and one event loop. Multi-process or distributed
deployment requires a transactional database and database-level concurrency control. See
[Concurrency and transactions](docs/concurrency_and_transactions.md).

## Persistence and audit

`ApplicationState` is the JSON source of truth. State writes use a temporary file, flush,
`fsync`, and atomic replacement. Each mutation stores its audit event in
`pending_audit_events`, a dictionary keyed by event ID, in the same commit. The outbox later
delivers complete JSONL records idempotently and removes them only after confirmed or already
completed delivery.

See [Persistence and audit](docs/persistence_and_audit.md).

## Optional OpenAI Agents SDK integration

The optional SDK layer supports `openai`, `gemini`, and `openai_compatible` model
configurations. `rule_based` remains the default. The SDK router produces locally validated
structured output, while specialist handoffs are limited to read-only fraud, security, and
explanation facts. No SDK function tool performs a financial mutation.

See [Provider configuration](docs/provider_configuration.md) and
[Prompt documentation](docs/prompts.md).

## Project structure

```text
.
|-- src/agentic_payments/       # Domain, application, agents, tools, infrastructure, CLI
|-- tests/                      # Unit, integration, concurrency, end-to-end, optional live
|-- scripts/                    # Notebook builder and validator
|-- docs/                       # Public design, safety, testing, and submission documents
|-- data/.gitkeep               # Placeholder; runtime files are ignored
|-- final_agentic_payment_project.ipynb
|-- pyproject.toml
|-- uv.lock
`-- .github/workflows/ci.yml
```

## Requirements

- Python 3.12 or newer.
- [uv](https://docs.astral.sh/uv/) for locked dependency and command execution.
- No provider credential for the default mode.
- Optional local credentials only when explicitly enabling an external provider.

## Installation

```powershell
uv sync --frozen
```

The complete development dependency set, including JupyterLab, is installed from
`pyproject.toml` and `uv.lock`; no separate manual Jupyter installation is required.

## Configuration

Defaults are read from `Settings`; `.env.example` lists supported names. Ordinary execution uses
`LLM_PROVIDER=rule_based` and `ENABLE_LLM_ROUTER=false`. Runtime state and audit paths default
under `data/`, but tests and the notebook use temporary directories.

Never put credentials in source, tests, documentation, or the notebook. For optional local-only
provider setup, follow [Provider configuration](docs/provider_configuration.md).

## Running the CLI

```powershell
uv run python -m agentic_payments --help
uv run python -m agentic_payments interactive
```

Console-script alternative:

```powershell
uv run agentic-payments --help
```

Interactive commands include `/help`, `/status`, `/flush`, `/reset`, and `/exit`. The
non-interactive CLI also exposes `status`, `flush`, and confirmed `reset --yes` subcommands.

## Running the demonstration

The demo uses temporary files and deterministic rule-based routing:

```powershell
uv run python -m agentic_payments demo
uv run agentic-payments demo
```

See [Execution examples](docs/execution_examples.md) for sanitized illustrative flows.

## Running the notebook

Open the interactive notebook from the repository root:

```powershell
uv run agentic-payments-notebook
```

This uses the current uv-managed Python environment, starts JupyterLab at the repository root,
and opens `final_agentic_payment_project.ipynb`.

Rebuild and execute the submitted notebook non-interactively:

```powershell
uv run python scripts/build_notebook.py
```

Validate structure, preserved outputs, repository-based imports, privacy, temporary-data
isolation, and clear failure outside the repository:

```powershell
uv run python scripts/validate_notebook.py
```

The artifact is [final_agentic_payment_project.ipynb](final_agentic_payment_project.ipynb).
See [Submission instructions](docs/submission.md).

### PyCharm

Select the shared **Run Final Notebook** Run Configuration and click **Run**. It executes
`uv sync --frozen` and then the uv-based notebook launcher. PyCharm interpreter registration
remains an IDE-local setting, but this shared configuration does not depend on manually selecting
or registering a Python interpreter.

## Running tests

```powershell
uv run pytest tests/unit tests/integration tests/concurrency tests/end_to_end -m "not live_llm"
```

Quality commands:

```powershell
uv run ruff check src scripts tests
uv run ruff format --check src scripts tests
uv run mypy src/agentic_payments scripts
```

Test layers and the historical Phase 10 totals are documented in
[Testing](docs/testing.md).

## Provider-specific live tests

Live tests are opt-in and excluded from standard tests and CI. They must be run only after the
user configures local credentials outside the repository:

```powershell
$env:RUN_LIVE_LLM_TESTS="true"
uv run pytest tests/live -m live_llm
```

Do not enable live tests for ordinary validation, notebook execution, or CI.

## Security and privacy

The system validates typed inputs and outputs, masks sensitive values in presentation output,
keeps SDK tools read-only, filters handoffs, and does not require provider secrets in CI. Local
runtime files and `.env` are ignored.

This is not a security boundary suitable for real money. See
[Security](docs/security.md) for the educational threat model and exclusions.

## Known limitations

- No production authentication or authorization model.
- No real bank, card, or payment-provider integration.
- JSON persistence and `asyncio` locks protect only one process and one event loop.
- Audit JSONL is not a state-replay mechanism.
- Optional LLM output is advisory and can fail independently of committed mutations.
- Local files do not replace a transactional database, backups, key management, or operational
  monitoring.

## Lecturer-requirement mapping

The project maps each lecturer requirement to concrete source files, tests, and a notebook
section in [Requirements traceability](docs/requirements_traceability.md).

## Documentation index

- [Architecture](docs/architecture.md)
- [Class design](docs/class_design.md)
- [Agent flows](docs/agent_flows.md)
- [Prompt documentation](docs/prompts.md)
- [Concurrency and transactions](docs/concurrency_and_transactions.md)
- [Persistence and audit](docs/persistence_and_audit.md)
- [Security](docs/security.md)
- [Testing](docs/testing.md)
- [Execution examples](docs/execution_examples.md)
- [Requirements traceability](docs/requirements_traceability.md)
- [Provider configuration](docs/provider_configuration.md)
- [Submission instructions](docs/submission.md)

## License

Licensed under the [MIT License](LICENSE).
