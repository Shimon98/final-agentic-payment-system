# Class Design

The tables document implemented public types and their principal public methods. “Financial
mutation” means direct authority to change wallets, transactions, requests, or the committed
aggregate.

## Domain

| Class | Purpose and public methods | Dependencies | Financial mutation |
|---|---|---|---|
| `User` | Immutable identity; `validate`, `to_dict`, `from_dict` | Aware `datetime` | No |
| `Wallet` | Immutable versioned balance; `can_debit`, `with_balance`, `credit`, `debit`, serialization | `Decimal`, aware `datetime` | Constructs updated values only |
| `Transaction` | Immutable transfer record; `with_risk_assessment`, serialization | Status and risk enums | Constructs updated values only |
| `PaymentRequest` | Pending/approved/rejected request; `is_pending`, `approve`, `reject`, serialization | Request status | Constructs updated values only |
| `AuditEvent` | Immutable auditable action; `to_dict`, `from_dict` | Aware `datetime`, safe details | No |
| `TransactionSnapshot` | Immutable transaction and before/after balance facts | `Transaction`, `Decimal` | No |
| `TransferPolicy` | Amount, single-limit, daily-limit, and balance-ratio rules | Prior transactions and configured limits | No |

The frozen entity methods return new values. They never publish application state by themselves.

## Application contracts and state

| Class | Purpose and public methods | Dependencies | Financial mutation |
|---|---|---|---|
| `AgentResult` | Shared `agent_name`, `output`, `confidence`, `metadata` result | Standard Python values | No |
| `RouterDecision` | Validated intent, parameters, confidence, and clarification | Pydantic, `Intent` | No |
| `FraudAssessment` | Validated score, level, reasons, and security flag | Pydantic, `RiskLevel` | No |
| `SecurityReview` | Validated read-only checks, violations, recommendations | Pydantic | No |
| `CriticReview` | Validated quality decision and fallback flag | Pydantic | No |
| `ReflectionAdvice` | Validated safe error guidance and suggested parameters | Pydantic | No |
| `RequestContext` | Correlation ID, idempotency key, aware request time, actor | Standard library | No |
| `ApplicationState` | Complete aggregate; `clone`, `validate_invariants`, serialization | Domain entities, memory, idempotency | Holds state; commits elsewhere |
| `BusinessMemory` | Last intent/tool/action/IDs/result and bounded recent actions | `MemoryEntry` | No financial mutation |
| `MemoryService` | `remember_route`, `remember_user`, `remember_transaction`, `remember_payment_request`, `remember_result`, `snapshot`, `reset` | State provider, caller-supplied aware times | Memory only |

Immutable command objects are `CreateUserCommand`, `CheckBalanceCommand`,
`TransferMoneyCommand`, `RequestPaymentCommand`, `ApprovePaymentCommand`,
`RejectPaymentCommand`, `ShowTransactionsCommand`, `FraudCheckCommand`,
`SecurityReviewCommand`, and `ExplainLastActionCommand`. Each carries an exact `RequestContext`;
commands validate types and values but do not execute operations.

## Application services

| Class | Purpose and public methods | Dependencies | Financial mutation |
|---|---|---|---|
| `PaymentDomainService` | `create_user`, `get_balance`, `get_transactions`, `transfer_money`, `request_payment`, `approve_payment_request`, `reject_payment_request`, `annotate_transaction_risk` | Transaction manager, locks, policy, clock, IDs | Yes; sole business mutation boundary |
| `PaymentFacade` | `create_user`, `check_balance`, `transfer_money`, `request_payment`, `approve_payment`, `reject_payment`, `show_transactions`, `fraud_check`, `security_review`, `explain_last_action`; coordinates policy and post-processing | Domain service, agents, memory | Only through domain service |
| `OrchestratorAgent` | `handle` routes, builds commands, guards, dispatches, criticizes, remembers, and flushes | Router, registry, guardrails, critic, reflection, fallback, outbox | Only through registry/facade/service |

Application LLM protocols are `LLMRouterGateway.route` and
`ReadOnlySpecialistGateway.run_specialist`. They isolate model infrastructure from the
orchestrator and expose no mutation method.

## Agents

| Class | Main public methods | Dependencies | Financial mutation |
|---|---|---|---|
| `RouterAgent` | `route`, `run` | Intent grammar, `RouterDecision` | No |
| `HybridRouterAgent` | `route`, `run` | LLM router protocol, deterministic router | No |
| `FraudDetectionAgent` | `assess_transaction`, `run` | Immutable snapshot, policy | No |
| `SecurityAgent` | `review_transaction`, `review_system`, `run` | Immutable snapshot or cloned state | No |
| `ExplanationAgent` | `explain_last_action`, `explain_transaction`, `run` | Business memory and stored facts | No |
| `CriticAgent` | `review`, `run` | `AgentResult`, expected intent | No |
| `PolicyAgent` | `evaluate_transfer`, `run` | Transfer policy and immutable facts | No |
| `ReflectionAgent` | `reflect_on_error`, `run` | Typed error and `AgentContext` | No |
| `FallbackAgent` | `handle_unknown`, `handle_low_confidence`, `request_missing_parameters`, `run` | Router decision | No |

`AgentContext` provides user input, correlation ID, aware request time, memory, optional routing
decision, and immutable payload facts. `BaseAgent` defines the common `name` and `run` contract.

## Tools

| Class | Purpose and public methods | Dependencies | Financial mutation |
|---|---|---|---|
| `PaymentToolRegistry` | `tool_name_for_intent`, `supported_intents`, `execute` | Exact command types, `PaymentFacade` | Only via facade |
| `ToolGuardrails` | `validate_before_execution`, `validate_after_execution` | Intent, command, `AgentResult` | No |

The registry has a static one-to-one mapping. It rejects `unknown` and exact-type mismatches.

| Intent | Tool name |
|---|---|
| `createUser` | `create_user_tool` |
| `checkBalance` | `check_balance_tool` |
| `transferMoney` | `transfer_money_tool` |
| `requestPayment` | `request_payment_tool` |
| `approvePayment` | `approve_payment_tool` |
| `rejectPayment` | `reject_payment_tool` |
| `showTransactions` | `show_transactions_tool` |
| `fraudCheck` | `fraud_check_tool` |
| `securityReview` | `security_review_tool` |
| `explainLastAction` | `explain_last_action_tool` |

## Infrastructure

| Class | Purpose and public methods | Dependencies | Financial mutation |
|---|---|---|---|
| `AsyncResourceLockManager` | `acquire`, `acquire_many` | `asyncio.Lock`, ordered `LockKey` | Synchronizes only |
| `PaymentTransactionManager` | `current_state`, `transaction` | State repository, global gate | Publishes validated UoW commits |
| `PaymentUnitOfWork` | `state`, `append_audit`, `validate_invariants`, `commit`, `rollback` | Working aggregate and commit callback | Stages and commits aggregate |
| `JsonStateRepository` | `load`, `save_atomic`, `reset` | Filesystem and `ApplicationState` serialization | Persists aggregate only |
| `JsonLinesAuditRepository` | `initialize`, `append`, `list_all`, `find_by_correlation_id`, `contains_event_id` | JSONL file and event index | Audit only |
| `AuditOutboxDispatcher` | `flush_pending` | Transaction manager, state and audit repositories | Removes confirmed outbox entries |
| `TransactionalIdempotencyStore` | `get`, `save` | Current UoW state | Idempotency records only |
| `Settings` | Validated environment-backed configuration; `build_transfer_policy` | Pydantic settings | No |
| `SystemClock` | `now` | UTC system clock | No |
| `UuidIdGenerator` | Five typed ID creation methods | UUID library | No |
| `AgentsModelFactory` | `is_enabled`, `provider_name`, `model_name`, `create_model` | Settings, SDK/OpenAI clients | No |
| `OpenAIAgentsRuntime` | `route`, `run_specialist` | Model factory, SDK agents and guardrails | No |

`OutboxFlushResult` reports attempted, delivered, already-delivered, removed, failed, and pending
counts without changing the meaning of a committed payment result.

## Presentation and composition

| Class or function | Purpose | Financial mutation |
|---|---|---|
| `ApplicationContainer` | Owns composed settings, repositories, locks, services, orchestrator, and startup status; `snapshot`, `flush_outbox`, `reset_state` | Reset/flush only through application infrastructure |
| `build_application` | Loads state, composes dependencies, and flushes startup outbox | No direct mutation |
| `build_parser`, `run_interactive`, `run_demo`, `main` | CLI command tree and event-loop boundary | Only through container/orchestrator |
| `format_agent_result`, `format_status`, `format_help` | Safe presentation formatting | No |

The CLI never accesses repositories to apply business rules.
