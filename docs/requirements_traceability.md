# Lecturer Requirements Traceability

Statuses below are supported by the named current source, tests, and executed notebook sections.

| Lecturer requirement | Implementation | Source files | Tests | Notebook section | Status |
|---|---|---|---|---|---|
| Shared `AgentResult` | Exact four-field dataclass used by every agent | `src/agentic_payments/application/results.py` | `tests/unit/test_application_results.py` | 9. Shared `AgentResult` structure | Done |
| Required intent set | `Intent` enum and typed routing schemas | `src/agentic_payments/domain/enums.py`<br>`src/agentic_payments/application/results.py` | `tests/unit/test_router_agent.py` | 12. Tools, guardrails, and memory | Done |
| `createUser` | Typed command, facade, locked service operation | `src/agentic_payments/application/commands.py`<br>`src/agentic_payments/application/payment_domain_service.py` | `tests/unit/test_payment_service_users.py` | 15. Scenario 1 | Done |
| `checkBalance` | Deterministic wallet read | `src/agentic_payments/application/payment_domain_service.py` | `tests/unit/test_payment_service_reads.py` | 15. Scenario 1 | Done |
| `transferMoney` | Atomic two-wallet transfer and snapshot | `src/agentic_payments/application/payment_domain_service.py` | `tests/unit/test_payment_service_transfers.py`<br>`tests/concurrency/test_payment_service_double_spending.py` | 15. Scenarios 2–6 | Done |
| `requestPayment` | Pending immutable request creation | `src/agentic_payments/application/payment_domain_service.py` | `tests/unit/test_payment_service_payment_requests.py` | 15. Scenario 7 | Done |
| `approvePayment` | Atomic approval, wallets, and transaction | `src/agentic_payments/application/payment_domain_service.py` | `tests/concurrency/test_payment_service_payment_requests.py` | 15. Scenarios 7–8 | Done |
| `rejectPayment` | Idempotent pending-to-rejected transition | `src/agentic_payments/application/payment_domain_service.py` | `tests/unit/test_payment_service_payment_requests.py` | 12. Tool mapping | Done |
| `showTransactions` | Newest-first user transaction read | `src/agentic_payments/application/payment_domain_service.py` | `tests/unit/test_payment_service_reads.py` | 14. Basic demonstration | Done |
| `fraudCheck` | Stored transaction to deterministic assessment | `src/agentic_payments/agents/fraud_agent.py` | `tests/unit/test_fraud_agent.py` | 16. Suspicious transaction | Done |
| `securityReview` | Transaction or aggregate read-only review | `src/agentic_payments/agents/security_agent.py` | `tests/unit/test_security_agent.py` | 16. Suspicious transaction | Done |
| `explainLastAction` | Stored memory and factual explanation | `src/agentic_payments/agents/explanation_agent.py`<br>`src/agentic_payments/application/memory_service.py` | `tests/unit/test_explanation_agent.py`<br>`tests/integration/test_orchestrator_memory.py` | 15. Scenario 10 | Done |
| `unknown` | Non-mutating fallback | `src/agentic_payments/agents/fallback_agent.py` | `tests/unit/test_fallback_agent.py` | 11. Agent responsibilities | Done |
| Positive finite amounts | Command and policy validation with `Decimal` | `src/agentic_payments/application/commands.py`<br>`src/agentic_payments/domain/policies.py` | `tests/unit/test_domain_policies.py` | 15. Scenario 3 | Done |
| Existing participants | Service requires users and wallets | `src/agentic_payments/application/payment_domain_service.py` | `tests/unit/test_payment_service_transfers.py` | 15. Scenario 5 | Done |
| No self-transfer | Command and domain participant validation | `src/agentic_payments/application/commands.py`<br>`src/agentic_payments/application/payment_domain_service.py` | `tests/unit/test_payment_service_transfers.py` | 15. Scenario 6 | Done |
| No negative balance | Locked debit and aggregate invariant | `src/agentic_payments/domain/entities.py`<br>`src/agentic_payments/application/state.py` | `tests/unit/test_domain_entities.py`<br>`tests/concurrency/test_payment_service_double_spending.py` | 15. Scenario 4 | Done |
| Transfer limits | `TransferPolicy` and service enforcement | `src/agentic_payments/domain/policies.py` | `tests/unit/test_domain_policies.py` | 17. PolicyAgent | Done |
| No duplicate request resolution | Status validation, request lock, idempotency | `src/agentic_payments/application/payment_domain_service.py` | `tests/concurrency/test_payment_service_payment_requests.py` | 15. Scenario 8 | Done |
| Audit log | Transactional outbox and idempotent JSONL delivery | `src/agentic_payments/infrastructure/audit_outbox.py`<br>`src/agentic_payments/infrastructure/jsonl_audit_repository.py` | `tests/integration/test_audit_outbox.py` | 17. Audit Outbox | Done |
| Expanded business memory | Last facts plus bounded recent actions | `src/agentic_payments/application/memory_service.py` | `tests/unit/test_memory_service.py` | 12 and 15.10 | Done |
| `RouterAgent` | Deterministic classification and extraction | `src/agentic_payments/agents/router_agent.py` | `tests/unit/test_router_agent.py` | 11. Agent responsibilities | Done |
| `OrchestratorAgent` | Complete request lifecycle | `src/agentic_payments/application/orchestrator.py` | `tests/integration/test_orchestrator_business_flows.py` | 4. Architecture | Done |
| `FraudDetectionAgent` | Deterministic post-transfer score | `src/agentic_payments/agents/fraud_agent.py` | `tests/unit/test_fraud_agent.py` | 16. Suspicious transaction | Done |
| `SecurityAgent` | Read-only consistency review | `src/agentic_payments/agents/security_agent.py` | `tests/unit/test_security_agent.py` | 16. Suspicious transaction | Done |
| `CriticAgent` | Result completeness and quality review | `src/agentic_payments/agents/critic_agent.py` | `tests/unit/test_critic_agent.py` | 11. Agent responsibilities | Done |
| `ExplanationAgent` | Factual last-action and transaction text | `src/agentic_payments/agents/explanation_agent.py` | `tests/unit/test_explanation_agent.py` | 15. Scenario 10 | Done |
| `FallbackAgent` | Unknown, low-confidence, and missing-input handling | `src/agentic_payments/agents/fallback_agent.py` | `tests/unit/test_fallback_agent.py` | 11. Agent responsibilities | Done |
| `PolicyAgent` | Advisory pre-transfer policy evaluation | `src/agentic_payments/agents/policy_agent.py` | `tests/unit/test_policy_agent.py` | 17. Advanced elements | Done |
| `ReflectionAgent` | Typed safe recovery guidance | `src/agentic_payments/agents/reflection_agent.py` | `tests/unit/test_reflection_agent.py` | 17. Advanced elements | Done |
| JSON persistence | Atomic state repository and restart | `src/agentic_payments/infrastructure/json_state_repository.py` | `tests/integration/test_json_state_repository.py`<br>`tests/end_to_end/test_end_to_end_restart.py` | 17. JSON persistence | Done |
| Tool selection | Static one-to-one intent mapping and exact commands | `src/agentic_payments/tools/payment_tools.py` | `tests/unit/test_payment_tools.py` | 12. Tools, guardrails, and memory | Done |
| At least eight tests | Unit, integration, concurrency, E2E, and notebook suites | `tests/conftest.py` | `tests/end_to_end/test_required_scenarios.py` | 15. Ten lecturer tests | Done |
| Ten explicit scenarios | Actual production flow with assertions and PASS output | `scripts/build_notebook.py` | `tests/integration/test_notebook_requirements.py` | 15. Ten lecturer tests | Done |
| Hebrew explanations | RTL-wrapped short Markdown | `scripts/build_notebook.py` | `tests/unit/test_notebook_structure.py` | All explanatory sections | Done |
| Final summary questions | Eight short reflection answers | `scripts/build_notebook.py` | `tests/integration/test_notebook_requirements.py` | 21. Summary questions | Done |
| Exact notebook filename | One root self-contained executed artifact | `final_agentic_payment_project.ipynb` | `tests/end_to_end/test_submission_notebook.py`<br>`tests/end_to_end/test_submission_notebook_portability.py` | Complete notebook | Done |
