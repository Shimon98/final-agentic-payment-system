# Execution Examples

All outputs below are illustrative and sanitized. Fictional IDs show result shape; they are not
claims about actual generated CLI output. Complete phone numbers are intentionally omitted.

## CLI help

```powershell
uv run python -m agentic_payments --help
```

Illustrative summary:

```text
usage: agentic-payments [-h] [--env-file PATH]
                        {interactive,demo,status,flush,reset} ...
```

## Deterministic demo

```powershell
uv run python -m agentic_payments demo
```

The demo creates temporary state, uses rule-based routing, performs a transfer, prints safe
results, and removes the temporary runtime.

## Interactive mode

```powershell
uv run python -m agentic_payments interactive
```

The deterministic router accepts a command form followed by `key=value` parameters.

## Create user

Illustrative input:

```text
createUser name=Alice phone_number=<masked-phone> initial_balance=500.00
```

Illustrative result facts:

```text
agent: PaymentFacade
user_id: USR-DEMO-ALICE
balance: 500.00 ILS
```

The real parser requires a valid local simulation phone value; presentation output masks it.

## Check balance

```text
checkBalance user_id=USR-DEMO-ALICE
```

Illustrative facts:

```text
user_id: USR-DEMO-ALICE
balance: 500.00
currency: ILS
```

## Transfer

```text
transferMoney sender_id=USR-DEMO-ALICE receiver_id=USR-DEMO-BOB amount=75.00
```

Illustrative facts:

```text
transaction_id: TXN-DEMO-001
status: COMPLETED
sender_balance: 425.00
receiver_balance: 275.00
risk_level: LOW
```

The IDs are fictional; actual IDs are generated locally.

## Payment request

```text
requestPayment requester_id=USR-DEMO-BOB payer_id=USR-DEMO-ALICE amount=25.00
```

Illustrative facts:

```text
request_id: REQ-DEMO-001
status: PENDING
```

## Approval

```text
approvePayment request_id=REQ-DEMO-001
```

Illustrative facts:

```text
request_status: APPROVED
related_transaction_id: TXN-DEMO-002
```

## Transaction history

```text
showTransactions user_id=USR-DEMO-ALICE
```

The result is newest first and contains stored transaction facts, not provider-generated
transactions.

## Fraud review

```text
fraudCheck transaction_id=TXN-DEMO-001
```

The deterministic agent returns score, level, reasons, and whether security review is required.

## Security review

```text
securityReview transaction_id=TXN-DEMO-001
```

Omitting the transaction ID requests a read-only aggregate review. Neither form changes state.

## Explanation

```text
explainLastAction
```

The explanation references persisted `BusinessMemory` and stored facts. Missing facts are
acknowledged rather than invented.

## Fallback

```text
do something unsupported
```

Illustrative behavior:

```text
The request was not mapped to a supported operation. No state was changed.
```

## Reflection

For a transfer larger than the available balance, the deterministic mutation fails before
commit. `ReflectionAgent` returns a safe error code, an explanation, recovery steps, and an
optional suggested amount. It does not retry the transfer.

## Status, flush, and reset

```powershell
uv run python -m agentic_payments status
uv run python -m agentic_payments flush
uv run python -m agentic_payments reset --yes
```

Interactive equivalents are `/status`, `/flush`, and `/reset`; interactive reset asks for exact
confirmation. Status contains aggregate counts and safe warnings only.

## No-API mode

No configuration change is needed. The defaults use rule-based routing:

```powershell
uv run python -m agentic_payments demo
uv run pytest tests/end_to_end -m "not live_llm"
```

No provider client or network request is created in this mode.
