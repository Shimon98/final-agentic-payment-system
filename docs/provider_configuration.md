# Provider Configuration

## Safe defaults

`rule_based` is the default mode. Ordinary CLI, demo, tests, and notebook execution require no
API key and make no provider request. Financial operations always remain deterministic, even when
model routing is enabled.

| Mode | Purpose | Required only when enabled |
|---|---|---|
| `rule_based` | Deterministic router and deterministic specialists | Nothing |
| `openai` | OpenAI Responses model for optional routing/specialists | Local model name and credential |
| `gemini` | Gemini through its OpenAI-compatible endpoint | Local model name and credential |
| `openai_compatible` | User-selected compatible endpoint | Local model name, base URL, and credential |

Provider configuration is optional. `ENABLE_LLM_ROUTER` must be true before
`AgentsModelFactory` is enabled. LLM routing is advisory: output is locally schema-validated and
can fall back to `RouterAgent`.

## Safe local setup

Only after optional live testing is deliberately approved:

1. Copy `.env.example` to the ignored local `.env`.
2. Add credentials only to `.env`.
3. Never commit `.env`.
4. Never place a key in the notebook.
5. Never place a key in README, tests, or source code.

Use placeholders in shared material:

```dotenv
LLM_PROVIDER=<rule_based-or-provider-name>
LLM_MODEL=<your-model-name>
LLM_API_KEY=<your-local-api-key>
LLM_BASE_URL=<your-compatible-base-url>
ENABLE_LLM_ROUTER=<true-or-false>
ENABLE_TRACING=<true-or-false>
```

`openai_compatible` requires a base URL when model routing is enabled. `gemini` can use the
implemented default compatible endpoint or a locally configured base URL. Tracing is separately
disabled by default.

## Read-only SDK boundary

The optional SDK router can classify. Specialist handoffs can only read authorized immutable
fraud, security, or explanation facts. SDK tools cannot create users, move money, approve or
reject requests, annotate risk, write repositories, or flush the outbox.

## Opt-in live tests

Live tests remain excluded unless a local operator has configured credentials and explicitly
sets:

```text
RUN_LIVE_LLM_TESTS=true
```

Then run:

```powershell
uv run pytest tests/live -m live_llm
```

Do not use this setting for ordinary tests, CI, or notebook validation. CI forces
`RUN_LIVE_LLM_TESTS=false`, `LLM_PROVIDER=rule_based`, and
`ENABLE_LLM_ROUTER=false`.

## Other configuration names

`Settings` also reads `APP_ENV`, `ROUTER_CONFIDENCE_THRESHOLD`, `STATE_FILE`, `AUDIT_FILE`,
`MAXIMUM_SINGLE_TRANSFER`, `MAXIMUM_DAILY_TRANSFER`, `SUSPICIOUS_BALANCE_RATIO`,
`RAPID_TRANSFER_WINDOW_MINUTES`, and `RAPID_TRANSFER_COUNT`. Values are validated before
application composition, and runtime file paths are created lazily.
