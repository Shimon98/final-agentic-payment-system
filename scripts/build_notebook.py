"""Build and execute the repository-based lecturer demonstration notebook."""

from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
import warnings
from collections.abc import Iterable, Sequence
from pathlib import Path
from textwrap import dedent

import nbformat
from nbclient import NotebookClient
from nbformat import NotebookNode

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "final_agentic_payment_project.ipynb"
DEFAULT_TIMEOUT = 600

SECTION_TITLES = (
    "1. כותרת ואזהרת סימולציה",
    "2. מבנה ההגשה ומטרות הפרויקט",
    "3. מיפוי דרישות המרצה",
    "4. ארכיטקטורה וגבולות אחריות",
    "5. הכנת סביבת הרצה מתוך המאגר",
    "6. המבנה המשותף AgentResult",
    "7. מודל הדומיין והסוכנים",
    "8. כלים, Guardrails וזיכרון עסקי",
    "9. בניית היישום",
    "10. הדגמה בסיסית",
    "11. עשרת תרחישי המרצה",
    "12. עסקה בסיכון גבוה",
    "13. רכיבים מתקדמים והתמדה",
    "14. בטיחות במקביליות",
    "15. OpenAI Agents SDK אופציונלי",
    "16. מגבלות",
    "17. שאלות סיכום",
    "18. אימות סופי וניקוי",
)

SCENARIO_TITLES = (
    "תרחיש 1 — יצירת שני משתמשים ובדיקת יתרות",
    "תרחיש 2 — העברת כסף מוצלחת",
    "תרחיש 3 — סכום העברה שלילי",
    "תרחיש 4 — יתרה לא מספקת",
    "תרחיש 5 — מקבל שאינו קיים",
    "תרחיש 6 — העברה עצמית",
    "תרחיש 7 — יצירה ואישור של בקשת תשלום",
    "תרחיש 8 — אישור חוזר של בקשה שהוכרעה",
    "תרחיש 9 — זיהוי עסקה חשודה",
    "תרחיש 10 — הסבר הפעולה האחרונה מזיכרון עסקי",
)

REQUIRED_PASS_LINES = (
    "PASS — create two users and check balances",
    "PASS — successful transfer",
    "PASS — negative transfer amount",
    "PASS — insufficient funds",
    "PASS — nonexistent receiver",
    "PASS — self transfer",
    "PASS — create and approve payment request",
    "PASS — approve already resolved payment request",
    "PASS — suspicious transaction detection",
    "PASS — explain last action using persisted BusinessMemory",
)


def _cell_id(kind: str, key: str) -> str:
    digest = hashlib.sha256(f"{kind}:{key}".encode()).hexdigest()[:16]
    return f"{kind[:8]}-{digest}"


def _clean_source(source: str) -> str:
    return dedent(source).strip() + "\n"


def _rtl(text: str) -> str:
    return (
        '<div dir="rtl" style="text-align: right; line-height: 1.7;">\n\n'
        f"{dedent(text).strip()}\n\n"
        "</div>"
    )


def add_markdown_section(
    notebook: NotebookNode,
    title: str,
    body: str,
    *,
    key: str,
) -> None:
    notebook.cells.append(
        nbformat.v4.new_markdown_cell(  # type: ignore[no-untyped-call]
            source=_rtl(f"## {title}\n\n{body}"),
            id=_cell_id("markdown", key),
        )
    )


def add_code_cell(notebook: NotebookNode, source: str, *, key: str) -> None:
    notebook.cells.append(
        nbformat.v4.new_code_cell(  # type: ignore[no-untyped-call]
            source=_clean_source(source),
            id=_cell_id("code", key),
        )
    )


def _add_intro(notebook: NotebookNode) -> None:
    add_markdown_section(
        notebook,
        SECTION_TITLES[0],
        """
        **סימולציה לימודית בלבד.**

        אין חיבור לבנק, לכרטיס אשראי או לספק תשלומים אמיתי.
        אין להשתמש בנתונים פיננסיים אמיתיים.

        הלוגיקה הכספית דטרמיניסטית. שכבת ה־LLM אופציונלית ומייעצת בלבד.
        """,
        key="title",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[1],
        """
        ההגשה כוללת את **המאגר המלא** ואת המחברת.

        - המימוש המלא נמצא תחת `src/agentic_payments/`.
        - המחברת היא הסבר והרצה של הקוד האמיתי מתוך המאגר.
        - אין במחברת העתק של קוד הייצור ואין שחזור של המאגר.

        מטרות הפרויקט הן תשלומים בטוחים בסביבה מקומית, סוכנים בעלי גבולות ברורים,
        התמדה אטומית, עקביות במקביליות והרצה מלאה ללא מפתח API.
        """,
        key="submission-role",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[2],
        """
        | דרישה | רכיב בפרויקט | הדגמה |
        |---|---|---|
        | תוצאה משותפת | `AgentResult` | הצגת קוד המקור בפועל |
        | ניתוב ותזמור | `RouterAgent`, `OrchestratorAgent` | עשרת התרחישים |
        | כלים וזיכרון | `PaymentToolRegistry`, `BusinessMemory` | מיפוי וכלי הסבר |
        | בדיקות סיכון | `FraudDetectionAgent`, `SecurityAgent` | עסקה בסיכון `HIGH` |
        | בקרת איכות | `CriticAgent`, `FallbackAgent` | כל תוצאת תזמור |
        | רכיבים מתקדמים | `PolicyAgent`, `ReflectionAgent` | דוגמאות ייעודיות |
        | בטיחות | Locks, Idempotency, Audit Outbox | התמדה ומקביליות |
        """,
        key="requirements",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[3],
        """
        ```text
        User → Router → Orchestrator → ToolGuardrails → PaymentFacade
                                                       ↓
                                              PaymentDomainService
                                                       ↓
                                      Locks → Unit of Work → JSON state
                                                       ↓
                                  Fraud / Security / Memory / Audit Outbox
        ```

        רק `PaymentDomainService` רשאי לשנות מצב כספי.
        הסוכנים מקבלים עובדות בלתי־משתנות ואינם משנים יתרות.
        """,
        key="architecture",
    )


def _add_setup(notebook: NotebookNode) -> None:
    add_markdown_section(
        notebook,
        SECTION_TITLES[4],
        """
        המחברת מיועדת להרצה משורש המאגר.
        תא ההכנה בודק את `src/agentic_payments/`, מוסיף את `src` ל־`sys.path`
        ויוצר את כל קובצי ההדגמה בתיקייה זמנית של מערכת ההפעלה.

        אם קוד המקור אינו קיים, מתקבלת הודעה ברורה במקום הורדה מהרשת.
        """,
        key="setup",
    )
    add_code_cell(
        notebook,
        """
        import asyncio
        import inspect
        import sys
        import tempfile
        from datetime import UTC, datetime
        from decimal import Decimal
        from pathlib import Path

        REPOSITORY_ROOT = Path.cwd().resolve()
        SOURCE_ROOT = REPOSITORY_ROOT / "src"
        if not (SOURCE_ROOT / "agentic_payments").is_dir():
            raise RuntimeError(
                "Run this notebook from the root of the submitted repository."
            )
        if str(SOURCE_ROOT) not in sys.path:
            sys.path.insert(0, str(SOURCE_ROOT))

        NOTEBOOK_RUNTIME = tempfile.TemporaryDirectory(
            prefix="agentic-payment-notebook-"
        )
        RUNTIME_ROOT = Path(NOTEBOOK_RUNTIME.name)
        DATA_ROOT = REPOSITORY_ROOT / "data"

        def data_snapshot():
            return {
                path.relative_to(DATA_ROOT).as_posix(): path.read_bytes()
                for path in DATA_ROOT.rglob("*")
                if path.is_file()
            }

        REPOSITORY_DATA_BEFORE = data_snapshot()

        from agentic_payments.agents import PolicyAgent
        from agentic_payments.application import AgentResult
        from agentic_payments.bootstrap import build_application
        from agentic_payments.domain import Intent
        from agentic_payments.infrastructure import Settings
        from agentic_payments.infrastructure.llm.sdk_guardrails import (
            _validate_tool_output,
        )
        from agentic_payments.tools.payment_tools import _TOOL_NAMES

        DEMO_TIME = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)

        def demo_phone(seed):
            return "050" + f"{seed:07d}"[-7:]

        async def isolated_container(label, **overrides):
            root = RUNTIME_ROOT / label
            root.mkdir(parents=True, exist_ok=True)
            values = {
                "app_env": "test",
                "llm_provider": "rule_based",
                "enable_llm_router": False,
                "state_file": root / "payment_state.json",
                "audit_file": root / "audit_log.jsonl",
            }
            values.update(overrides)
            settings = Settings(_env_file=None, **values)
            return await build_application(settings), settings

        async def create_demo_user(container, name, seed, balance, key):
            return await container.orchestrator.handle(
                (
                    f'createUser name="{name}" phone={demo_phone(seed)} '
                    f"initial_balance={balance}"
                ),
                correlation_id=f"COR-{key}",
                idempotency_key=f"IDEM-{key}",
                requested_at=DEMO_TIME,
            )

        print("Repository package import success: yes")
        print("Repository-based source of truth: src/agentic_payments")
        print("Temporary runtime isolation: yes")
        """,
        key="repository-setup",
    )


def _add_types_agents_and_tools(notebook: NotebookNode) -> None:
    add_markdown_section(
        notebook,
        SECTION_TITLES[5],
        """
        כל סוכן מחזיר `AgentResult` באותו מבנה.
        התא הבא מציג את ההצהרה האמיתית מתוך `src`, באמצעות `inspect.getsource()`.
        """,
        key="agent-result",
    )
    add_code_cell(
        notebook,
        """
        agent_result_source = inspect.getsource(AgentResult)
        assert "agent_name" in agent_result_source
        assert "output" in agent_result_source
        assert "confidence" in agent_result_source
        assert "metadata" in agent_result_source
        print(agent_result_source)
        """,
        key="agent-result-source",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[6],
        """
        | רכיב | אחריות |
        |---|---|
        | `User` | זהות משתמש וטלפון מנורמל |
        | `Wallet` | יתרה בלתי־משתנה וגרסה עולה |
        | `Transaction` | העברה, סטטוס והערכת סיכון |
        | `PaymentRequest` | בקשת תשלום ומעבר מצב חד־כיווני |
        | `TransferPolicy` | סכום חיובי, מגבלות והיקף יומי |

        | סוכן | אחריות |
        |---|---|
        | `RouterAgent` | סיווג וחילוץ פרמטרים |
        | `OrchestratorAgent` | תזמור בקשה אחת וכלי ראשי אחד |
        | `FraudDetectionAgent` | ציון סיכון דטרמיניסטי |
        | `SecurityAgent` | בדיקת עקביות לקריאה בלבד |
        | `ExplanationAgent` | הסבר מעובדות הזיכרון |
        | `CriticAgent` | בדיקת איכות התוצאה |
        | `PolicyAgent` | עצת מדיניות לפני פעולה |
        | `ReflectionAgent` | התאוששות בטוחה משגיאה |
        | `FallbackAgent` | חסימת בקשה לא ברורה |
        """,
        key="domain-agents",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[7],
        """
        מיפוי הכלים קבוע: לכל intent נתמך יש כלי אחד.
        `BusinessMemory` שומר את הכוונה, המשתמש, העסקה, הבקשה והתוצאה האחרונה.

        ה־Guardrails דוחים כסף שמקורו ב־float, סודות, הוראות ביצוע ומספרי טלפון מלאים.
        תאריך ISO תקין ומודע לאזור זמן מותר רק בשדה זמן מאושר.
        """,
        key="tools-memory",
    )
    add_code_cell(
        notebook,
        """
        tool_rows = [
            (intent.value, _TOOL_NAMES[intent])
            for intent in Intent
            if intent in _TOOL_NAMES
        ]
        assert len(tool_rows) == 10
        print("Intent-to-tool mapping:")
        for intent_name, tool_name in tool_rows:
            print(f"  {intent_name:20} -> {tool_name}")

        _validate_tool_output(
            {"requested_at": DEMO_TIME.isoformat(), "facts": {"status": "safe"}}
        )
        phone_rejected = False
        try:
            _validate_tool_output(
                {"facts": {"contact": demo_phone(9876543)}}
            )
        except ValueError:
            phone_rejected = True
        assert phone_rejected
        print("Guardrail aware datetime: PASS")
        print("Guardrail complete-phone rejection: PASS")
        """,
        key="tool-mapping-guardrails",
    )


def _add_bootstrap_and_basic_demo(notebook: NotebookNode) -> None:
    add_markdown_section(
        notebook,
        SECTION_TITLES[8],
        """
        `build_application()` טוען מצב, יוצר מנהל נעילות ועסקאות, בונה שירות דומיין,
        סוכנים, כלים, זיכרון ו־Audit Outbox.

        ההגדרה כאן היא `rule_based`; אין מפתח API ואין אובייקט ספק.
        """,
        key="bootstrap",
    )
    add_code_cell(
        notebook,
        """
        demo_container, demo_settings = await isolated_container("basic")
        assert demo_settings.llm_api_key is None
        assert demo_container.llm_runtime is None
        print("Application bootstrap: PASS")
        print("Provider client constructed: no")
        """,
        key="bootstrap-code",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[9],
        """
        הדגמה קצרה מפעילה את ה־`OrchestratorAgent` האמיתי:
        יצירת שני משתמשים, בדיקת יתרה, העברה והצגת היסטוריה.
        הפלט מציג רק סיכום ואינו מציג טלפונים או metadata מלא.
        """,
        key="basic-demo",
    )
    add_code_cell(
        notebook,
        """
        basic_alice = await create_demo_user(
            demo_container, "Basic Alice", 101, "1000.00", "BASIC-A"
        )
        basic_bob = await create_demo_user(
            demo_container, "Basic Bob", 102, "200.00", "BASIC-B"
        )
        basic_alice_id = basic_alice.output["user_id"]
        basic_bob_id = basic_bob.output["user_id"]
        basic_balance = await demo_container.orchestrator.handle(
            f"checkBalance user_id={basic_alice_id}",
            requested_at=DEMO_TIME,
        )
        basic_transfer = await demo_container.orchestrator.handle(
            (
                f"transferMoney sender_id={basic_alice_id} "
                f"receiver_id={basic_bob_id} amount=125.00"
            ),
            idempotency_key="IDEM-BASIC-TRANSFER",
            requested_at=DEMO_TIME,
        )
        basic_history = await demo_container.orchestrator.handle(
            f"showTransactions user_id={basic_alice_id}",
            requested_at=DEMO_TIME,
        )
        assert basic_balance.output["balance"] == "1000.00"
        assert basic_transfer.output["snapshot"]["sender_balance_after"] == "875.00"
        assert len(basic_history.output["transactions"]) == 1
        print("Basic demo: balance 1000.00 -> 875.00")
        print("Basic demo: one persisted transaction")
        """,
        key="basic-demo-code",
    )


def _scenario_markdown(first: int, second: int) -> str:
    return _rtl(
        f"### {SCENARIO_TITLES[first - 1]}\n\n"
        "הרצה דרך `OrchestratorAgent` עם assertions.\n\n"
        f"### {SCENARIO_TITLES[second - 1]}\n\n"
        "הרצה דרך `OrchestratorAgent` עם assertions."
    )


def _add_scenarios(notebook: NotebookNode) -> None:
    add_markdown_section(
        notebook,
        SECTION_TITLES[10],
        """
        כל תרחיש מפעיל את זרימת ה־production.
        כשל עסקי צפוי חוזר כ־`ReflectionAgent`; חריגה לא צפויה אינה מוסתרת.
        """,
        key="scenarios",
    )
    notebook.cells.append(
        nbformat.v4.new_markdown_cell(  # type: ignore[no-untyped-call]
            source=_scenario_markdown(1, 2),
            id=_cell_id("markdown", "scenarios-1-2"),
        )
    )
    add_code_cell(
        notebook,
        """
        scenario_container, scenario_settings = await isolated_container("lecturer")
        scenario_alice = await create_demo_user(
            scenario_container, "Scenario Alice", 201, "1000.00", "S1-A"
        )
        scenario_bob = await create_demo_user(
            scenario_container, "Scenario Bob", 202, "200.00", "S1-B"
        )
        scenario_alice_id = scenario_alice.output["user_id"]
        scenario_bob_id = scenario_bob.output["user_id"]
        balance_a = await scenario_container.orchestrator.handle(
            f"checkBalance user_id={scenario_alice_id}", requested_at=DEMO_TIME
        )
        balance_b = await scenario_container.orchestrator.handle(
            f"checkBalance user_id={scenario_bob_id}", requested_at=DEMO_TIME
        )
        assert balance_a.output["balance"] == "1000.00"
        assert balance_b.output["balance"] == "200.00"
        print("PASS — create two users and check balances")

        scenario_transfer = await scenario_container.orchestrator.handle(
            (
                f"transferMoney sender_id={scenario_alice_id} "
                f"receiver_id={scenario_bob_id} amount=125.00"
            ),
            idempotency_key="IDEM-S2",
            requested_at=DEMO_TIME,
        )
        assert scenario_transfer.output["snapshot"]["sender_balance_after"] == "875.00"
        assert scenario_transfer.output["snapshot"]["receiver_balance_after"] == "325.00"
        print("PASS — successful transfer")
        """,
        key="scenarios-1-2-code",
    )
    notebook.cells.append(
        nbformat.v4.new_markdown_cell(  # type: ignore[no-untyped-call]
            source=_scenario_markdown(3, 4),
            id=_cell_id("markdown", "scenarios-3-4"),
        )
    )
    add_code_cell(
        notebook,
        """
        negative = await scenario_container.orchestrator.handle(
            (
                f"transferMoney sender_id={scenario_alice_id} "
                f"receiver_id={scenario_bob_id} amount=-1.00"
            ),
            idempotency_key="IDEM-S3",
            requested_at=DEMO_TIME,
        )
        assert negative.agent_name == "ReflectionAgent"
        assert negative.output.error_code == "value_error"
        print("PASS — negative transfer amount")

        insufficient = await scenario_container.orchestrator.handle(
            (
                f"transferMoney sender_id={scenario_alice_id} "
                f"receiver_id={scenario_bob_id} amount=2000.00"
            ),
            idempotency_key="IDEM-S4",
            requested_at=DEMO_TIME,
        )
        assert insufficient.agent_name == "ReflectionAgent"
        assert insufficient.output.error_code == "insufficient_funds"
        print("PASS — insufficient funds")
        """,
        key="scenarios-3-4-code",
    )
    notebook.cells.append(
        nbformat.v4.new_markdown_cell(  # type: ignore[no-untyped-call]
            source=_scenario_markdown(5, 6),
            id=_cell_id("markdown", "scenarios-5-6"),
        )
    )
    add_code_cell(
        notebook,
        """
        missing_receiver = await scenario_container.orchestrator.handle(
            (
                f"transferMoney sender_id={scenario_alice_id} "
                "receiver_id=USR-MISSING amount=1.00"
            ),
            idempotency_key="IDEM-S5",
            requested_at=DEMO_TIME,
        )
        assert missing_receiver.agent_name == "ReflectionAgent"
        assert missing_receiver.output.error_code == "user_not_found"
        print("PASS — nonexistent receiver")

        self_transfer = await scenario_container.orchestrator.handle(
            (
                f"transferMoney sender_id={scenario_alice_id} "
                f"receiver_id={scenario_alice_id} amount=1.00"
            ),
            idempotency_key="IDEM-S6",
            requested_at=DEMO_TIME,
        )
        assert self_transfer.agent_name == "ReflectionAgent"
        assert self_transfer.output.error_code == "value_error"
        print("PASS — self transfer")
        """,
        key="scenarios-5-6-code",
    )
    notebook.cells.append(
        nbformat.v4.new_markdown_cell(  # type: ignore[no-untyped-call]
            source=_scenario_markdown(7, 8),
            id=_cell_id("markdown", "scenarios-7-8"),
        )
    )
    add_code_cell(
        notebook,
        """
        payment_request = await scenario_container.orchestrator.handle(
            (
                f"requestPayment requester_id={scenario_bob_id} "
                f"payer_id={scenario_alice_id} amount=30.00"
            ),
            idempotency_key="IDEM-S7-REQUEST",
            requested_at=DEMO_TIME,
        )
        scenario_request_id = payment_request.output["payment_request_id"]
        approved_request = await scenario_container.orchestrator.handle(
            f"approvePayment request_id={scenario_request_id}",
            idempotency_key="IDEM-S7-APPROVE",
            requested_at=DEMO_TIME,
        )
        assert approved_request.output["payment_request"]["status"] == "APPROVED"
        print("PASS — create and approve payment request")

        resolved_again = await scenario_container.orchestrator.handle(
            f"approvePayment request_id={scenario_request_id}",
            idempotency_key="IDEM-S8-DIFFERENT",
            requested_at=DEMO_TIME,
        )
        assert resolved_again.agent_name == "ReflectionAgent"
        assert resolved_again.output.error_code == "payment_request_already_resolved"
        print("PASS — approve already resolved payment request")
        """,
        key="scenarios-7-8-code",
    )
    notebook.cells.append(
        nbformat.v4.new_markdown_cell(  # type: ignore[no-untyped-call]
            source=_scenario_markdown(9, 10),
            id=_cell_id("markdown", "scenarios-9-10"),
        )
    )
    add_code_cell(
        notebook,
        """
        high_container, high_settings = await isolated_container(
            "high-risk",
            maximum_single_transfer=Decimal("5000.00"),
            maximum_daily_transfer=Decimal("10000.00"),
        )
        high_source = await create_demo_user(
            high_container, "High Source", 301, "5000.00", "S9-SOURCE"
        )
        high_target = await create_demo_user(
            high_container, "High Target", 302, "0.00", "S9-TARGET"
        )
        high_source_id = high_source.output["user_id"]
        high_target_id = high_target.output["user_id"]
        high_result = await high_container.orchestrator.handle(
            (
                f"transferMoney sender_id={high_source_id} "
                f"receiver_id={high_target_id} amount=4000.00"
            ),
            idempotency_key="IDEM-S9-RISK",
            requested_at=DEMO_TIME,
        )
        high_tx_id = high_result.output["transaction_id"]
        high_assessment = high_result.output["fraud_assessment"]
        assert high_assessment["risk_level"] == "HIGH"
        assert high_result.output["snapshot"]["transaction"]["status"] == "FLAGGED"
        assert high_result.output["security_review"] is not None
        print("PASS — suspicious transaction detection")

        high_restart = await build_application(high_settings)
        assert high_restart.memory_service.snapshot().last_transaction_id == high_tx_id
        explanation = await high_restart.orchestrator.handle(
            "explainLastAction",
            requested_at=DEMO_TIME,
        )
        assert explanation.output["facts"]["output"]["transaction_id"] == high_tx_id
        print("PASS — explain last action using persisted BusinessMemory")
        """,
        key="scenarios-9-10-code",
    )
    add_code_cell(
        notebook,
        """
        LECTURER_SCENARIOS_PASSED = True
        print("10/10 lecturer scenarios passed")
        """,
        key="scenario-summary",
    )


def _add_advanced_features(notebook: NotebookNode) -> None:
    add_markdown_section(
        notebook,
        SECTION_TITLES[11],
        """
        העברה של 4000 מתוך 5000 עוברת את ספי הכמות ויחס היתרה.
        `FraudDetectionAgent` מסמן `HIGH`; לאחר מכן `SecurityAgent` בודק את העובדות.
        """,
        key="high-risk",
    )
    add_code_cell(
        notebook,
        """
        assert high_assessment["risk_score"] >= 60
        assert high_assessment["risk_level"] == "HIGH"
        assert high_result.output["snapshot"]["transaction"]["status"] == "FLAGGED"
        assert high_result.output["security_review"]["approved"] is True
        print(
            "HIGH-risk demo:",
            f"score={high_assessment['risk_score']}",
            "level=HIGH",
            "status=FLAGGED",
        )
        """,
        key="high-risk-code",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[12],
        """
        `PolicyAgent` נותן עצה לפני פעולה.
        `ReflectionAgent` ממיר שגיאת דומיין להנחיית התאוששות בלי לבצע retry.

        מצב JSON, זיכרון עסקי, idempotency ואירועי Audit Outbox נשמרים בתיקייה הזמנית.
        """,
        key="advanced",
    )
    add_code_cell(
        notebook,
        """
        policy_agent = PolicyAgent(
            transfer_policy=high_settings.build_transfer_policy()
        )
        policy_review = await policy_agent.evaluate_transfer(
            sender_id=high_source_id,
            amount=Decimal("6000.00"),
            balance_before=Decimal("10000.00"),
            previous_transactions=(),
            now=DEMO_TIME,
        )
        assert policy_review.output.approved is False
        assert "policy_violation" in policy_review.output.violations
        assert insufficient.agent_name == "ReflectionAgent"
        assert insufficient.output.recovery_steps
        print("PolicyAgent over-limit rejection: PASS")
        print("ReflectionAgent safe recovery advice: PASS")
        """,
        key="policy-reflection",
    )
    add_code_cell(
        notebook,
        """
        restarted_state = high_restart.snapshot()
        assert len(restarted_state.users) == 2
        assert high_tx_id in restarted_state.transactions
        assert restarted_state.memory.last_transaction_id == high_tx_id
        PERSISTENCE_PASSED = True
        print("PASS — JSON persistence and BusinessMemory survived restart")

        outbox_result = await high_restart.flush_outbox()
        audit_events = await high_restart.audit_repository.list_all()
        assert outbox_result.pending_after == 0
        assert audit_events
        assert not high_restart.snapshot().pending_audit_events
        OUTBOX_PASSED = True
        print("PASS — Audit Outbox delivered all temporary audit events")
        """,
        key="persistence-outbox",
    )


def _add_concurrency(notebook: NotebookNode) -> None:
    add_markdown_section(
        notebook,
        SECTION_TITLES[13],
        """
        ההדגמה מריצה שלושה מצבים אמיתיים:

        1. שתי משיכות מתחרות מאותה יתרה.
        2. שתי הפקדות מתחרות לאותו ארנק.
        3. העברות בכיוונים מנוגדים תחת timeout.

        סדר נעילות דטרמיניסטי מונע deadlock.
        ההבטחה היא לתהליך Python ול־event loop יחידים.
        """,
        key="concurrency",
    )
    add_code_cell(
        notebook,
        """
        withdraw_container, _ = await isolated_container("concurrent-withdraw")
        withdraw_source = await create_demo_user(
            withdraw_container, "Withdraw Source", 401, "100.00", "CW-S"
        )
        withdraw_a = await create_demo_user(
            withdraw_container, "Withdraw A", 402, "0.00", "CW-A"
        )
        withdraw_b = await create_demo_user(
            withdraw_container, "Withdraw B", 403, "0.00", "CW-B"
        )
        source_id = withdraw_source.output["user_id"]
        withdraw_results = await asyncio.gather(
            withdraw_container.orchestrator.handle(
                (
                    f"transferMoney sender_id={source_id} "
                    f"receiver_id={withdraw_a.output['user_id']} amount=80.00"
                ),
                idempotency_key="IDEM-CW-1",
                requested_at=DEMO_TIME,
            ),
            withdraw_container.orchestrator.handle(
                (
                    f"transferMoney sender_id={source_id} "
                    f"receiver_id={withdraw_b.output['user_id']} amount=80.00"
                ),
                idempotency_key="IDEM-CW-2",
                requested_at=DEMO_TIME,
            ),
        )
        successes = [
            item for item in withdraw_results
            if isinstance(item.output, dict)
            and item.output.get("operation") == "transferMoney"
        ]
        reflections = [
            item for item in withdraw_results
            if item.agent_name == "ReflectionAgent"
        ]
        assert len(successes) == 1 and len(reflections) == 1
        assert withdraw_container.snapshot().wallets[source_id].balance == Decimal("20.00")

        deposit_container, _ = await isolated_container("concurrent-deposit")
        deposit_one = await create_demo_user(
            deposit_container, "Deposit One", 411, "100.00", "CD-1"
        )
        deposit_two = await create_demo_user(
            deposit_container, "Deposit Two", 412, "100.00", "CD-2"
        )
        deposit_target = await create_demo_user(
            deposit_container, "Deposit Target", 413, "20.00", "CD-T"
        )
        deposit_results = await asyncio.gather(
            deposit_container.orchestrator.handle(
                (
                    f"transferMoney sender_id={deposit_one.output['user_id']} "
                    f"receiver_id={deposit_target.output['user_id']} amount=100.00"
                ),
                idempotency_key="IDEM-CD-X1",
                requested_at=DEMO_TIME,
            ),
            deposit_container.orchestrator.handle(
                (
                    f"transferMoney sender_id={deposit_two.output['user_id']} "
                    f"receiver_id={deposit_target.output['user_id']} amount=100.00"
                ),
                idempotency_key="IDEM-CD-X2",
                requested_at=DEMO_TIME,
            ),
        )
        deposit_summary = [
            (
                item.agent_name,
                item.output.get("operation")
                if isinstance(item.output, dict)
                else getattr(item.output, "error_code", type(item.output).__name__),
            )
            for item in deposit_results
        ]
        assert all(
            isinstance(item.output, dict)
            and item.output.get("operation") == "transferMoney"
            for item in deposit_results
        ), deposit_summary
        target_id = deposit_target.output["user_id"]
        assert deposit_container.snapshot().wallets[target_id].balance == Decimal("220.00")

        opposite_container, _ = await isolated_container("opposite")
        opposite_a = await create_demo_user(
            opposite_container, "Opposite A", 421, "100.00", "CO-A"
        )
        opposite_b = await create_demo_user(
            opposite_container, "Opposite B", 422, "100.00", "CO-B"
        )
        opposite_results = await asyncio.wait_for(
            asyncio.gather(
                opposite_container.orchestrator.handle(
                    (
                        f"transferMoney sender_id={opposite_a.output['user_id']} "
                        f"receiver_id={opposite_b.output['user_id']} amount=10.00"
                    ),
                    idempotency_key="IDEM-CO-1",
                    requested_at=DEMO_TIME,
                ),
                opposite_container.orchestrator.handle(
                    (
                        f"transferMoney sender_id={opposite_b.output['user_id']} "
                        f"receiver_id={opposite_a.output['user_id']} amount=10.00"
                    ),
                    idempotency_key="IDEM-CO-2",
                    requested_at=DEMO_TIME,
                ),
            ),
            timeout=2.0,
        )
        assert len(opposite_results) == 2
        CONCURRENCY_PASSED = True
        print("Double-spending final balance: 20.00")
        print("Lost-update final target balance: 220.00")
        print("Opposite transfers timeout: PASS")
        print("PASS — concurrency safety demonstrations")
        """,
        key="concurrency-code",
    )


def _add_sdk_and_final(notebook: NotebookNode) -> None:
    add_markdown_section(
        notebook,
        SECTION_TITLES[14],
        """
        שכבת ה־SDK היא אופציונלית.
        הנתב יכול להשתמש בפלט מובנה, ושלושה handoffs לקריאה בלבד זמינים לבדיקת הונאה,
        אבטחה והסבר.

        בהרצה הרגילה של המחברת לא נוצר provider client ולא נשלחת בקשת רשת.
        אין כלי SDK שמבצע פעולה כספית.
        """,
        key="sdk",
    )
    add_code_cell(
        notebook,
        """
        from agents import AgentOutputSchema
        from agentic_payments.infrastructure.llm.sdk_agents import (
            _router_agent,
            _specialist_agents,
        )

        sdk_router = _router_agent("not-executed")
        sdk_specialists = _specialist_agents("not-executed")
        sdk_tools = [
            tool.name
            for agent in (
                sdk_specialists.fraud,
                sdk_specialists.security,
                sdk_specialists.explanation,
            )
            for tool in agent.tools
        ]
        assert isinstance(sdk_router.output_type, AgentOutputSchema)
        assert sdk_router.output_type.is_strict_json_schema() is False
        assert sdk_tools == [
            "get_fraud_review_facts",
            "get_security_review_facts",
            "get_last_action_facts",
        ]
        assert not any(
            marker in " ".join(sdk_tools)
            for marker in ("transfer", "approve", "create_user")
        )
        print("Optional SDK router schema: locally validated, non-strict provider schema")
        print("Read-only SDK tools:", ", ".join(sdk_tools))
        print("Financial function tool present: no")
        print("Live provider request made: no")
        """,
        key="sdk-code",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[15],
        """
        - זו מערכת לימודית ואינה פלטפורמה בנקאית.
        - קובצי JSON ונעילות asyncio מגינים על תהליך ו־event loop יחידים.
        - מערכת מרובת תהליכים דורשת מסד נתונים טרנזקציוני.
        - Audit Log אינו מנגנון replay.
        - פלט LLM הוא מייעץ; חוקי הכסף נשארים דטרמיניסטיים.
        """,
        key="limitations",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[16],
        """
        **מה עבד היטב?**

        גבולות שכבות, `Decimal`, זיכרון עסקי, idempotency ו־Audit Outbox.

        **מדוע נדרשים גם locks וגם idempotency?**

        Locks מגינים מפעולות מקבילות; idempotency מונע ביצוע חוזר של retry זהה.

        **מתי שירות ענן מתאים?**

        כאשר נדרשים מודלים חזקים וזמינות מנוהלת, בכפוף למדיניות פרטיות.

        **מדוע אין צורך במפתח API?**

        הנתב הדטרמיניסטי וכל חוקי התשלום פועלים מקומית.
        """,
        key="summary",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[17],
        """
        האימות האחרון מרכז את תוצאות התרחישים, ההתמדה, המקביליות והבידוד.
        התא שאחריו מנקה את התיקייה הזמנית והוא התא האחרון במחברת.
        """,
        key="final-validation",
    )
    add_code_cell(
        notebook,
        """
        final_outbox = await high_restart.flush_outbox()
        REPOSITORY_DATA_AFTER = data_snapshot()
        FINAL_CHECKS = {
            "repository source imported": (SOURCE_ROOT / "agentic_payments").is_dir(),
            "all ten lecturer scenarios passed": LECTURER_SCENARIOS_PASSED,
            "persistence restart passed": PERSISTENCE_PASSED,
            "outbox passed": OUTBOX_PASSED and final_outbox.pending_after == 0,
            "concurrency passed": CONCURRENCY_PASSED,
            "no API key used": demo_settings.llm_api_key is None,
            "no provider client": demo_container.llm_runtime is None,
            "repository data untouched": REPOSITORY_DATA_AFTER == REPOSITORY_DATA_BEFORE,
        }
        assert all(FINAL_CHECKS.values())
        for label, passed in FINAL_CHECKS.items():
            print(f"PASS — {label}: {'yes' if passed else 'no'}")
        print("FINAL NOTEBOOK VALIDATION PASSED")
        """,
        key="final-validation-code",
    )
    add_code_cell(
        notebook,
        """
        NOTEBOOK_RUNTIME.cleanup()
        assert not RUNTIME_ROOT.exists()
        print("Temporary notebook runtime cleaned successfully.")
        """,
        key="cleanup-final-cell",
    )


def create_notebook() -> NotebookNode:
    """Create the deterministic unexecuted repository-based notebook."""

    notebook: NotebookNode = nbformat.v4.new_notebook()  # type: ignore[no-untyped-call]
    notebook.metadata = {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {
            "name": "python",
            "version": "3.12",
        },
        "agentic_payments_notebook_role": "repository-based-demonstration",
    }
    _add_intro(notebook)
    _add_setup(notebook)
    _add_types_agents_and_tools(notebook)
    _add_bootstrap_and_basic_demo(notebook)
    _add_scenarios(notebook)
    _add_advanced_features(notebook)
    _add_concurrency(notebook)
    _add_sdk_and_final(notebook)
    return notebook


def _execute_notebook(
    notebook: NotebookNode,
    *,
    timeout: int,
    workdir: Path = REPOSITORY_ROOT,
) -> NotebookNode:
    client = NotebookClient(
        notebook,
        timeout=timeout,
        kernel_name="python3",
        resources={"metadata": {"path": str(workdir)}},
        record_timing=False,
        allow_errors=False,
    )
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Proactor event loop does not implement add_reader.*",
            category=RuntimeWarning,
        )
        return client.execute()


def _atomic_write_notebook(
    notebook: NotebookNode,
    output_path: Path,
    *,
    execute: bool,
    timeout: int,
) -> NotebookNode:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=output_path.parent,
    )
    os.close(descriptor)
    staging_path = Path(staging_name)
    try:
        final_notebook = (
            _execute_notebook(notebook, timeout=timeout, workdir=REPOSITORY_ROOT)
            if execute
            else notebook
        )
        nbformat.write(final_notebook, staging_path)  # type: ignore[no-untyped-call]
        os.replace(staging_path, output_path)
        return final_notebook
    finally:
        staging_path.unlink(missing_ok=True)


def build_notebook(
    output_path: Path = DEFAULT_OUTPUT,
    *,
    execute: bool = True,
    timeout: int = DEFAULT_TIMEOUT,
) -> NotebookNode:
    """Build, optionally execute, and atomically publish the notebook."""

    if not isinstance(output_path, Path):
        raise TypeError("output_path must be a Path")
    if output_path.name != DEFAULT_OUTPUT.name:
        raise ValueError("submission notebook filename must be exact")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise ValueError("timeout must be a positive integer")
    return _atomic_write_notebook(
        create_notebook(),
        output_path,
        execute=execute,
        timeout=timeout,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the repository-based agentic payment demonstration notebook."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Exact output notebook path.",
    )
    parser.add_argument(
        "--no-execute",
        action="store_true",
        help="Build an unexecuted notebook.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help="Per-cell execution timeout.",
    )
    return parser


def _count_cells(cells: Iterable[NotebookNode], cell_type: str) -> int:
    return sum(cell.cell_type == cell_type for cell in cells)


def _code_metrics(notebook: NotebookNode) -> tuple[int, int]:
    line_counts = [
        len(str(cell.source).splitlines()) for cell in notebook.cells if cell.cell_type == "code"
    ]
    return sum(line_counts), max(line_counts, default=0)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    notebook = build_notebook(
        arguments.output,
        execute=not arguments.no_execute,
        timeout=arguments.timeout,
    )
    total_lines, maximum_lines = _code_metrics(notebook)
    print(
        "Notebook built successfully:",
        arguments.output.name,
        f"cells={len(notebook.cells)}",
        f"code={_count_cells(notebook.cells, 'code')}",
        f"markdown={_count_cells(notebook.cells, 'markdown')}",
        f"code_lines={total_lines}",
        f"max_code_cell_lines={maximum_lines}",
        f"executed={'no' if arguments.no_execute else 'yes'}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
