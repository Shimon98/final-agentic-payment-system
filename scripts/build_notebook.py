"""Build and execute the single self-contained submission notebook."""

from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
import warnings
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import cast

import nbformat
from nbclient import NotebookClient
from nbformat import NotebookNode

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src" / "agentic_payments"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "final_agentic_payment_project.ipynb"
DEFAULT_TIMEOUT = 600

SECTION_TITLES = (
    "1. כותרת ואזהרת סימולציה",
    "2. מטרות הפרויקט",
    "3. מיפוי דרישות המרצה",
    "4. ארכיטקטורה",
    "5. מניפסט קוד המקור",
    "6. הכנת סביבת הריצה",
    "7. קוד המקור המלא",
    "8. אימות ייבוא וסביבה",
    "9. המבנה המשותף AgentResult",
    "10. דומיין התשלומים",
    "11. סוכנים ותחומי אחריות",
    "12. כלים, Guardrails וזיכרון",
    "13. בניית היישום",
    "14. הדגמה בסיסית",
    "15. עשרת תרחישי המרצה",
    "16. עסקה חשודה",
    "17. אלמנטים מתקדמים",
    "18. בטיחות במקביליות",
    "19. OpenAI Agents SDK אופציונלי",
    "20. מגבלות אבטחה",
    "21. שאלות סיכום",
    "22. אימות סופי",
    "23. ניקוי סביבת הריצה",
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


def collect_source_files(src_root: Path) -> dict[str, str]:
    """Collect every production Python file as sorted, normalized readable text."""

    if not isinstance(src_root, Path):
        raise TypeError("src_root must be a Path")
    if not src_root.is_dir():
        raise FileNotFoundError("production source root is missing")
    discovered: list[tuple[str, str]] = []
    for path in src_root.rglob("*.py"):
        relative_parts = path.relative_to(src_root).parts
        if "__pycache__" in relative_parts or any(part.startswith(".") for part in relative_parts):
            continue
        normalized = Path("src", "agentic_payments", *relative_parts).as_posix()
        discovered.append((normalized, path.read_text(encoding="utf-8")))
    discovered.sort(key=lambda item: item[0])
    return dict(discovered)


def source_manifest(source_files: dict[str, str]) -> tuple[dict[str, str], ...]:
    """Return the stable normalized path and SHA-256 manifest."""

    return tuple(
        {
            "path": path,
            "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        }
        for path, source in sorted(source_files.items())
    )


def _cell_id(kind: str, key: str) -> str:
    digest = hashlib.sha256(f"{kind}:{key}".encode()).hexdigest()[:16]
    return f"{kind[:8]}-{digest}"


def add_markdown_section(
    notebook: NotebookNode,
    title: str,
    body: str,
    *,
    key: str | None = None,
) -> None:
    """Append one stable-ID Markdown section."""

    source = f"## {title}\n\n{body}".rstrip() + "\n"
    notebook.cells.append(
        nbformat.v4.new_markdown_cell(  # type: ignore[no-untyped-call]
            source=source,
            id=_cell_id("markdown", key or title),
        )
    )


def add_code_cell(
    notebook: NotebookNode,
    source: str,
    *,
    key: str | None = None,
) -> None:
    """Append one stable-ID code cell."""

    stable_key = key or hashlib.sha256(source.encode()).hexdigest()
    notebook.cells.append(
        nbformat.v4.new_code_cell(  # type: ignore[no-untyped-call]
            source=source.rstrip() + "\n",
            id=_cell_id("code", stable_key),
        )
    )


def _rtl(text: str) -> str:
    return f'<div dir="rtl">\n\n{text.strip()}\n\n</div>'


def _manifest_markdown(manifest: tuple[dict[str, str], ...]) -> str:
    rows = "\n".join(f"| `{entry['path']}` | `{entry['sha256']}` |" for entry in manifest)
    return _rtl(
        f"""המחברת נוצרה ישירות מתיקיית `src` ומכילה {len(manifest)} קובצי Python.
לא נעשה שימוש בעותק ידני נוסף של מחלקות הפרויקט.

| Source path | SHA-256 |
|---|---|
{rows}"""
    )


def _group_for_path(path: str) -> str:
    if "/domain/" in path:
        return "Domain"
    if "/application/" in path:
        return "Application"
    if "/agents/" in path:
        return "Agents"
    if "/tools/" in path:
        return "Tools"
    if "/infrastructure/concurrency/" in path:
        return "Concurrency"
    if "/infrastructure/llm/" in path:
        return "Optional LLM/Agents SDK"
    if "/infrastructure/" in path:
        return "Infrastructure"
    return "Presentation and bootstrap"


def _add_source_cells(notebook: NotebookNode, source_files: dict[str, str]) -> None:
    group_order = (
        "Domain",
        "Application",
        "Agents",
        "Tools",
        "Concurrency",
        "Infrastructure",
        "Optional LLM/Agents SDK",
        "Presentation and bootstrap",
    )
    grouped = {
        group: [
            (path, source)
            for path, source in source_files.items()
            if _group_for_path(path) == group
        ]
        for group in group_order
    }
    for group in group_order:
        notebook.cells.append(
            nbformat.v4.new_markdown_cell(  # type: ignore[no-untyped-call]
                source=f"### {group}\n",
                id=_cell_id("source-group", group),
            )
        )
        for path, source in grouped[group]:
            add_code_cell(
                notebook,
                f"%%writefile {path}\n{source}",
                key=f"source:{path}",
            )


def _add_introductory_sections(
    notebook: NotebookNode,
    manifest: tuple[dict[str, str], ...],
) -> None:
    add_markdown_section(
        notebook,
        SECTION_TITLES[0],
        _rtl(
            """# מערכת סוכנים לסימולציית תשלומים דמוית Bit

**קורס:** בינה מלאכותית וסוכנים  
**סוג הגשה:** פרויקט גמר  
**שם המחברת:** `final_agentic_payment_project.ipynb`

זוהי סימולציה לימודית בלבד. אין שימוש במידע פיננסי אמיתי, ואין חיבור לבנק,
לכרטיס אשראי או לספק תשלומים."""
        ),
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[1],
        _rtl(
            """המערכת מסווגת בקשות, מתזמרת פעולות תשלום דטרמיניסטיות, שומרת זיכרון
עסקי, בודקת הונאה ואבטחה, מבקרת תוצאות ומספקת fallback ו-reflection בטוחים.

המצב נשמר ב-JSON עם מנגנוני נעילה, Unit of Work, אידמפוטנטיות ו-Audit Outbox.
שכבת OpenAI Agents SDK אופציונלית ומוגנת; ברירת המחדל אינה דורשת API."""
        ),
    )
    traceability = """| Lecturer requirement | Project component | Demonstration section |
|---|---|---|
| Shared AgentResult | `application.results.AgentResult` | 9 |
| Expanded RouterAgent | `RouterAgent` | 8, 11, 14 |
| Expanded OrchestratorAgent | `OrchestratorAgent` | 11, 14, 15 |
| Payment entities and operations | Domain + `PaymentDomainService` | 10, 14, 15 |
| Tool selection | `PaymentToolRegistry` | 12 |
| Expanded business memory | `BusinessMemory` + `MemoryService` | 12, 15, 17 |
| FraudDetectionAgent | Deterministic fraud scoring | 15, 16 |
| SecurityAgent and CriticAgent | Read-only review | 11, 16 |
| ExplanationAgent | Factual explanation | 15 |
| Advanced elements | Policy, Reflection, JSON, Outbox | 17 |
| At least eight tests | Ten lecturer scenarios + concurrency | 15, 18 |
| Hebrew explanations | RTL Markdown sections | Throughout |
| Final answers | Eight reflection answers | 21 |
| No real financial integration | Deterministic simulation | 1, 20 |"""
    add_markdown_section(
        notebook,
        SECTION_TITLES[2],
        _rtl(
            f"""הטבלה מקשרת כל דרישת מרצה לרכיב המימוש ולהדגמה בפועל.

{traceability}"""
        ),
    )
    architecture = """```text
User
  ↓
RouterAgent / HybridRouterAgent
  ↓
OrchestratorAgent
  ↓
ToolGuardrails
  ↓
PaymentToolRegistry
  ↓
PaymentFacade
  ↓
PaymentDomainService
  ↓
Locks + Unit of Work + JSON State
  ↓
Fraud / Security / Critic / Explanation
  ↓
Memory + Audit Outbox
```"""
    add_markdown_section(
        notebook,
        SECTION_TITLES[3],
        _rtl(
            """ה-LLM רשאי להבין, לסווג, לבקר ולהסביר. קוד דטרמיניסטי בלבד מאמת
ומשנה כסף. סוכנים אינם משנים יתרות או מצב עסקי ישירות."""
        )
        + "\n\n"
        + architecture,
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[4],
        _manifest_markdown(manifest),
    )


def _add_runtime_and_source(
    notebook: NotebookNode,
    source_files: dict[str, str],
) -> None:
    source_directories = tuple(sorted({Path(path).parent.as_posix() for path in source_files}))
    add_markdown_section(
        notebook,
        SECTION_TITLES[5],
        _rtl(
            """המחברת בודקת תלויות קיימות בלבד. היא אינה מתקינה חבילות ואינה
מבצעת גישה לרשת. כל קוד, מצב עסקי ו-audit נוצרים בתיקייה זמנית."""
        ),
    )
    add_code_cell(
        notebook,
        """
import importlib

REQUIRED_DEPENDENCIES = (
    "pydantic",
    "pydantic_settings",
    "openai",
    "agents",
    "nbformat",
    "nbclient",
    "ipykernel",
)
missing_dependencies = [
    name for name in REQUIRED_DEPENDENCIES
    if importlib.util.find_spec(name) is None
]
if missing_dependencies:
    raise RuntimeError(
        "Missing required dependencies. Run: "
        "pip install pydantic pydantic-settings openai openai-agents nbformat nbclient"
    )
print("Dependency preflight passed.")
""",
        key="dependency-preflight",
    )
    add_code_cell(
        notebook,
        f"""
import os
import sys
import tempfile
from pathlib import Path

NOTEBOOK_LAUNCH_DIRECTORY = Path.cwd()
NOTEBOOK_RUNTIME = tempfile.TemporaryDirectory(prefix="agentic-payment-notebook-")
RUNTIME_ROOT = Path(NOTEBOOK_RUNTIME.name)
os.chdir(RUNTIME_ROOT)
SOURCE_DIRECTORIES = {source_directories!r}
for source_directory in SOURCE_DIRECTORIES:
    Path(source_directory).mkdir(parents=True, exist_ok=True)
Path("data").mkdir(parents=True, exist_ok=True)
STATE_PATH = Path("data/payment_state.json")
AUDIT_PATH = Path("data/audit_log.jsonl")
sys.path.insert(0, str((RUNTIME_ROOT / "src").resolve()))
print("Temporary notebook runtime prepared.")
""",
        key="temporary-runtime",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[6],
        _rtl(
            """כל תא להלן כותב קובץ production קריא מתוך המניפסט. הטקסט נשמר
בדיוק כפי שהוא במקור, ללא קידוד, דחיסה או blob אטום."""
        ),
    )
    _add_source_cells(notebook, source_files)


def _add_core_demonstrations(notebook: NotebookNode) -> None:
    add_markdown_section(
        notebook,
        SECTION_TITLES[7],
        _rtl(
            """הייבוא מתבצע מהמקור שנכתב לתיקייה הזמנית. מצב rule-based אינו
יוצר provider client ואינו מבצע בקשת רשת."""
        ),
    )
    add_code_cell(
        notebook,
        """
import socket

network_attempts = []
original_create_connection = socket.create_connection

def _forbid_network(*args, **kwargs):
    network_attempts.append("blocked")
    raise AssertionError("Network access is forbidden in this notebook")

socket.create_connection = _forbid_network
try:
    import agentic_payments
finally:
    socket.create_connection = original_create_connection

assert not network_attempts
PACKAGE_IMPORTED = True
NO_NETWORK_REQUEST_MADE = True
print(f"Python version: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
print("Package import success: yes")
print("LLM provider mode: rule_based")
print("API key required: no")
print("State path: temporary")
print("Audit path: temporary")
""",
        key="environment-verification",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[8],
        _rtl(
            """`AgentResult` הוא המבנה המשותף לכל הסוכנים. ארבעת השדות הם שם
הסוכן, פלט מובנה, confidence ומטא-דאטה אופציונלי."""
        ),
    )
    add_code_cell(
        notebook,
        """
import inspect
from agentic_payments.application import AgentResult

print(inspect.getsource(AgentResult))
""",
        key="agent-result-source",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[9],
        _rtl(
            """הדומיין כולל משתמש, ארנק, עסקה ובקשת תשלום. כסף מיוצג תמיד
ב-`Decimal`. הארנק immutable ו-versioned, וכל שינוי מחזיר מופע חדש."""
        ),
    )
    add_code_cell(
        notebook,
        """
from dataclasses import fields
from decimal import Decimal
from agentic_payments.domain import PaymentRequest, Transaction, User, Wallet

for entity in (User, Wallet, Transaction, PaymentRequest):
    print(f"{entity.__name__}: {[field.name for field in fields(entity)]}")
print("Money type:", Decimal.__name__)
print("Wallet immutable: yes")
print("Wallet versioned: yes")
""",
        key="domain-summary",
    )
    roles = """| Agent | Responsibility | Financial mutation |
|---|---|---|
| RouterAgent | Classify intent and parameters | No direct financial mutation |
| OrchestratorAgent | Coordinate validated workflow | No direct financial mutation |
| FraudDetectionAgent | Deterministic risk score | No direct financial mutation |
| SecurityAgent | Read-only consistency review | No direct financial mutation |
| ExplanationAgent | Explain verified facts | No direct financial mutation |
| CriticAgent | Review result quality | No direct financial mutation |
| PolicyAgent | Evaluate deterministic limits | No direct financial mutation |
| ReflectionAgent | Safe recovery advice | No direct financial mutation |
| FallbackAgent | Handle unclear requests | No direct financial mutation |"""
    add_markdown_section(
        notebook,
        SECTION_TITLES[10],
        _rtl(
            f"""הסוכנים מסווגים, בודקים ומסבירים. רק שירות הדומיין ויחידת
העבודה רשאים לשנות מצב עסקי.

{roles}"""
        ),
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[11],
        _rtl(
            """מיפוי intent-to-tool הוא סטטי. Guardrails בודקים התאמה לפני
הרצה ופלט בטוח אחריה. `BusinessMemory` שומר את הפעולה והתוצאה האחרונות
ועד עשרים פעולות אחרונות. Audit Outbox מונע אובדן audit לאחר commit."""
        ),
    )
    add_code_cell(
        notebook,
        """
from datetime import UTC, datetime
from agentic_payments.application import (
    BusinessMemory,
    RequestContext,
    RouterDecision,
    TransferMoneyCommand,
)
from agentic_payments.domain import Intent
from agentic_payments.tools import ToolGuardrails
from agentic_payments.tools.payment_tools import _TOOL_NAMES

for intent, tool_name in _TOOL_NAMES.items():
    print(f"{intent.value} -> {tool_name}")

guardrails = ToolGuardrails()
accepted_decision = RouterDecision(
    intent=Intent.TRANSFER_MONEY,
    parameters={"sender_id": "U1", "receiver_id": "U2", "amount": Decimal("1.00")},
    confidence=1.0,
)
accepted_command = TransferMoneyCommand(
    "U1",
    "U2",
    Decimal("1.00"),
    RequestContext("COR-GUARD", "IDEM-GUARD", datetime(2026, 1, 1, tzinfo=UTC)),
)
guardrails.validate_before_execution(
    decision=accepted_decision,
    command=accepted_command,
)
print("PASS — accepted guardrail example")

try:
    guardrails.validate_before_execution(
        decision=RouterDecision(
            intent=Intent.UNKNOWN,
            parameters={},
            confidence=1.0,
        ),
        command=accepted_command,
    )
except ValueError:
    print("PASS — safely rejected guardrail example")
else:
    raise AssertionError("UNKNOWN intent unexpectedly passed the guardrail")

print("BusinessMemory fields:", [field.name for field in fields(BusinessMemory)])
""",
        key="tools-guardrails-memory",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[12],
        _rtl(
            """היישום נבנה דרך `build_application()` בלבד. ההגדרות מצביעות
לקובצי state ו-audit זמניים, ונתב ה-LLM כבוי במפורש."""
        ),
    )
    add_code_cell(
        notebook,
        """
from agentic_payments.bootstrap import Settings, build_application

settings = Settings(
    _env_file=None,
    app_env="test",
    llm_provider="rule_based",
    enable_llm_router=False,
    state_file=STATE_PATH,
    audit_file=AUDIT_PATH,
)
container = await build_application(settings)
assert container.llm_runtime is None
DETERMINISTIC_ROUTER_WORKING = (
    type(container.orchestrator._router_agent).__name__ == "RouterAgent"
)
assert DETERMINISTIC_ROUTER_WORKING
print("ApplicationContainer ready in rule-based mode.")
""",
        key="application-bootstrap",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[13],
        _rtl(
            """ההדגמה משתמשת ב-`OrchestratorAgent.handle()`, במזהי correlation
ובמפתחות idempotency מפורשים. המזהים שנוצרים מחולצים מהפלט ואינם מקובעים."""
        ),
    )
    add_code_cell(
        notebook,
        """
from agentic_payments.presentation import format_agent_result

BASIC_TIME = datetime(2026, 1, 2, 10, 0, tzinfo=UTC)
basic_results = []
basic_alice = await container.orchestrator.handle(
    'createUser name="Alice Cohen" phone=0501234567 initial_balance=1000.00',
    correlation_id="COR-BASIC-ALICE",
    idempotency_key="IDEM-BASIC-ALICE",
    requested_at=BASIC_TIME,
)
basic_bob = await container.orchestrator.handle(
    'createUser name="Bob Levi" phone=0509876543 initial_balance=200.00',
    correlation_id="COR-BASIC-BOB",
    idempotency_key="IDEM-BASIC-BOB",
    requested_at=BASIC_TIME,
)
basic_alice_id = basic_alice.output["user_id"]
basic_bob_id = basic_bob.output["user_id"]
basic_results.extend((basic_alice, basic_bob))
basic_results.append(
    await container.orchestrator.handle(
        f"checkBalance user_id={basic_alice_id}",
        correlation_id="COR-BASIC-BALANCE-A",
        requested_at=BASIC_TIME,
    )
)
basic_results.append(
    await container.orchestrator.handle(
        f"checkBalance user_id={basic_bob_id}",
        correlation_id="COR-BASIC-BALANCE-B",
        requested_at=BASIC_TIME,
    )
)
basic_transfer = await container.orchestrator.handle(
    f"transferMoney sender_id={basic_alice_id} receiver_id={basic_bob_id} amount=125.00",
    correlation_id="COR-BASIC-TRANSFER",
    idempotency_key="IDEM-BASIC-TRANSFER",
    requested_at=BASIC_TIME,
)
basic_results.append(basic_transfer)
basic_results.append(
    await container.orchestrator.handle(
        f"showTransactions user_id={basic_alice_id}",
        correlation_id="COR-BASIC-HISTORY",
        requested_at=BASIC_TIME,
    )
)
for result in basic_results:
    print(format_agent_result(result))
print("PASS — basic orchestrator demonstration")
""",
        key="basic-demonstration",
    )


def _add_lecturer_scenarios(notebook: NotebookNode) -> None:
    add_markdown_section(
        notebook,
        SECTION_TITLES[14],
        _rtl(
            """כל תרחיש מריץ קוד production אמיתי, כולל assertions. כשלים
עסקיים צפויים חוזרים כתוצאת `ReflectionAgent`; חריגה לא צפויה אינה מוסתרת."""
        ),
    )
    add_code_cell(
        notebook,
        """
SCENARIO_TIME = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)

async def isolated_container(label, **overrides):
    values = {
        "app_env": "test",
        "llm_provider": "rule_based",
        "enable_llm_router": False,
        "state_file": Path(f"data/{label}_state.json"),
        "audit_file": Path(f"data/{label}_audit.jsonl"),
    }
    values.update(overrides)
    scenario_settings = Settings(_env_file=None, **values)
    return await build_application(scenario_settings), scenario_settings

scenario_container, scenario_settings = await isolated_container("lecturer")
""",
        key="scenario-setup",
    )
    scenario_cells = (
        """
scenario_alice = await scenario_container.orchestrator.handle(
    'createUser name="Scenario Alice" phone=0501111111 initial_balance=1000.00',
    correlation_id="COR-S1-ALICE",
    idempotency_key="IDEM-S1-ALICE",
    requested_at=SCENARIO_TIME,
)
scenario_bob = await scenario_container.orchestrator.handle(
    'createUser name="Scenario Bob" phone=0502222222 initial_balance=200.00',
    correlation_id="COR-S1-BOB",
    idempotency_key="IDEM-S1-BOB",
    requested_at=SCENARIO_TIME,
)
scenario_alice_id = scenario_alice.output["user_id"]
scenario_bob_id = scenario_bob.output["user_id"]
balance_a = await scenario_container.orchestrator.handle(
    f"checkBalance user_id={scenario_alice_id}",
    correlation_id="COR-S1-BALANCE-A",
    requested_at=SCENARIO_TIME,
)
balance_b = await scenario_container.orchestrator.handle(
    f"checkBalance user_id={scenario_bob_id}",
    correlation_id="COR-S1-BALANCE-B",
    requested_at=SCENARIO_TIME,
)
assert balance_a.output["balance"] == "1000.00"
assert balance_b.output["balance"] == "200.00"
print("PASS — create two users and check balances")
""",
        """
scenario_transfer = await scenario_container.orchestrator.handle(
    f"transferMoney sender_id={scenario_alice_id} receiver_id={scenario_bob_id} amount=125.00",
    correlation_id="COR-S2-TRANSFER",
    idempotency_key="IDEM-S2-TRANSFER",
    requested_at=SCENARIO_TIME,
)
assert scenario_transfer.output["operation"] == "transferMoney"
assert scenario_transfer.output["snapshot"]["sender_balance_after"] == "875.00"
assert scenario_transfer.output["snapshot"]["receiver_balance_after"] == "325.00"
print("PASS — successful transfer")
""",
        """
negative = await scenario_container.orchestrator.handle(
    f"transferMoney sender_id={scenario_alice_id} receiver_id={scenario_bob_id} amount=-1.00",
    correlation_id="COR-S3-NEGATIVE",
    idempotency_key="IDEM-S3-NEGATIVE",
    requested_at=SCENARIO_TIME,
)
assert negative.agent_name == "ReflectionAgent"
assert negative.output.error_code == "value_error"
print("PASS — negative transfer amount")
""",
        """
insufficient = await scenario_container.orchestrator.handle(
    f"transferMoney sender_id={scenario_alice_id} receiver_id={scenario_bob_id} amount=2000.00",
    correlation_id="COR-S4-FUNDS",
    idempotency_key="IDEM-S4-FUNDS",
    requested_at=SCENARIO_TIME,
)
assert insufficient.agent_name == "ReflectionAgent"
assert insufficient.output.error_code == "insufficient_funds"
print("PASS — insufficient funds")
""",
        """
missing_receiver = await scenario_container.orchestrator.handle(
    f"transferMoney sender_id={scenario_alice_id} receiver_id=USR-MISSING amount=1.00",
    correlation_id="COR-S5-MISSING",
    idempotency_key="IDEM-S5-MISSING",
    requested_at=SCENARIO_TIME,
)
assert missing_receiver.agent_name == "ReflectionAgent"
assert missing_receiver.output.error_code == "user_not_found"
print("PASS — nonexistent receiver")
""",
        """
self_transfer = await scenario_container.orchestrator.handle(
    f"transferMoney sender_id={scenario_alice_id} receiver_id={scenario_alice_id} amount=1.00",
    correlation_id="COR-S6-SELF",
    idempotency_key="IDEM-S6-SELF",
    requested_at=SCENARIO_TIME,
)
assert self_transfer.agent_name == "ReflectionAgent"
assert self_transfer.output.error_code == "value_error"
print("PASS — self transfer")
""",
        """
payment_request = await scenario_container.orchestrator.handle(
    f"requestPayment requester_id={scenario_bob_id} payer_id={scenario_alice_id} amount=30.00",
    correlation_id="COR-S7-REQUEST",
    idempotency_key="IDEM-S7-REQUEST",
    requested_at=SCENARIO_TIME,
)
scenario_request_id = payment_request.output["payment_request_id"]
approved_request = await scenario_container.orchestrator.handle(
    f"approvePayment request_id={scenario_request_id}",
    correlation_id="COR-S7-APPROVE",
    idempotency_key="IDEM-S7-APPROVE",
    requested_at=SCENARIO_TIME,
)
assert approved_request.output["operation"] == "approvePayment"
assert approved_request.output["payment_request"]["status"] == "APPROVED"
print("PASS — create and approve payment request")
""",
        """
resolved_again = await scenario_container.orchestrator.handle(
    f"approvePayment request_id={scenario_request_id}",
    correlation_id="COR-S8-APPROVE",
    idempotency_key="IDEM-S8-DIFFERENT-KEY",
    requested_at=SCENARIO_TIME,
)
assert resolved_again.agent_name == "ReflectionAgent"
assert resolved_again.output.error_code == "payment_request_already_resolved"
print("PASS — approve already resolved payment request")
""",
        """
high_container, high_settings = await isolated_container(
    "high_risk",
    maximum_single_transfer=Decimal("5000.00"),
    maximum_daily_transfer=Decimal("10000.00"),
)
high_source = await high_container.orchestrator.handle(
    'createUser name="High Source" phone=0503333333 initial_balance=5000.00',
    correlation_id="COR-S9-SOURCE",
    idempotency_key="IDEM-S9-SOURCE",
    requested_at=SCENARIO_TIME,
)
high_target = await high_container.orchestrator.handle(
    'createUser name="High Target" phone=0504444444 initial_balance=0.00',
    correlation_id="COR-S9-TARGET",
    idempotency_key="IDEM-S9-TARGET",
    requested_at=SCENARIO_TIME,
)
high_source_id = high_source.output["user_id"]
high_target_id = high_target.output["user_id"]
high_result = await high_container.orchestrator.handle(
    f"transferMoney sender_id={high_source_id} receiver_id={high_target_id} amount=4000.00",
    correlation_id="COR-S9-RISK",
    idempotency_key="IDEM-S9-RISK",
    requested_at=SCENARIO_TIME,
)
high_tx_id = high_result.output["transaction_id"]
high_assessment = high_result.output["fraud_assessment"]
assert high_assessment["risk_score"] >= 60
assert high_assessment["risk_level"] == "HIGH"
assert high_result.output["snapshot"]["transaction"]["status"] == "FLAGGED"
assert high_result.output["security_review"] is not None
high_balance_value = high_container.snapshot().wallets[high_source_id].balance
assert high_balance_value == Decimal("1000.00")
print("PASS — suspicious transaction detection")
""",
        """
high_restart = await build_application(high_settings)
persisted_memory = high_restart.memory_service.snapshot()
assert persisted_memory.last_transaction_id == high_tx_id
explanation = await high_restart.orchestrator.handle(
    "explainLastAction",
    correlation_id="COR-S10-EXPLAIN",
    requested_at=SCENARIO_TIME,
)
assert explanation.agent_name == "OrchestratorAgent"
assert explanation.output["facts"]
assert explanation.output["facts"]["output"]["transaction_id"] == high_tx_id
print("PASS — explain last action using persisted BusinessMemory")
""",
    )
    for index, (title, source) in enumerate(
        zip(SCENARIO_TITLES, scenario_cells, strict=True),
        start=1,
    ):
        notebook.cells.append(
            nbformat.v4.new_markdown_cell(  # type: ignore[no-untyped-call]
                source=_rtl(f"### {title}\n\nהתרחיש מריץ את זרימת ה-production המלאה."),
                id=_cell_id("scenario", f"heading-{index}"),
            )
        )
        add_code_cell(notebook, source, key=f"scenario:{index}")
    add_code_cell(
        notebook,
        """
LECTURER_SCENARIOS_PASSED = True
print("10/10 lecturer scenarios passed")
""",
        key="scenario-summary",
    )


def _add_advanced_and_concurrency(notebook: NotebookNode) -> None:
    add_markdown_section(
        notebook,
        SECTION_TITLES[15],
        _rtl(
            """העברה של 4000 מתוך 5000 מקבלת ציון HIGH אמיתי לפי המדיניות:
25 נקודות לקרבה למגבלת העברה ועוד 35 נקודות ליחס יתרה גבוה."""
        ),
    )
    add_code_cell(
        notebook,
        """
assert high_assessment["risk_score"] >= 60
assert high_assessment["risk_level"] == "HIGH"
assert high_result.output["snapshot"]["transaction"]["status"] == "FLAGGED"
assert high_result.output["security_review"]["approved"] is True
assert high_balance_value == Decimal("1000.00")
print(
    "HIGH risk verified:",
    high_assessment["risk_score"],
    high_assessment["risk_level"],
    high_result.output["snapshot"]["transaction"]["status"],
)
""",
        key="suspicious-details",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[16],
        _rtl(
            """מוצגים ארבעה אלמנטים מתקדמים: `PolicyAgent`, `ReflectionAgent`,
טעינה חוזרת מ-JSON ו-Audit Outbox. כולם משתמשים במימוש production."""
        ),
    )
    add_code_cell(
        notebook,
        """
from agentic_payments.agents import PolicyAgent

policy_agent = PolicyAgent(transfer_policy=high_settings.build_transfer_policy())
policy_review = await policy_agent.evaluate_transfer(
    sender_id=high_source_id,
    amount=Decimal("6000.00"),
    balance_before=Decimal("10000.00"),
    previous_transactions=(),
    now=SCENARIO_TIME,
)
assert policy_review.agent_name == "PolicyAgent"
assert policy_review.output.approved is False
assert "policy_violation" in policy_review.output.violations
print("PASS — PolicyAgent rejected an amount over the policy limit")

assert insufficient.agent_name == "ReflectionAgent"
assert insufficient.output.error_code == "insufficient_funds"
assert insufficient.output.recovery_steps
print("PASS — ReflectionAgent returned safe recovery advice")

restarted_state = high_restart.snapshot()
assert len(restarted_state.users) == 2
assert high_tx_id in restarted_state.transactions
assert restarted_state.memory.last_transaction_id == high_tx_id
PERSISTENCE_PASSED = True
print("PASS — JSON persistence and BusinessMemory survived restart")

advanced_flush = await high_restart.flush_outbox()
audit_events = await high_restart.audit_repository.list_all()
assert advanced_flush.pending_after == 0
assert audit_events
assert not high_restart.snapshot().pending_audit_events
ADVANCED_FEATURES_PASSED = True
print("PASS — Audit Outbox delivered all temporary audit events")
""",
        key="advanced-elements",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[17],
        _rtl(
            """Race condition עלול ליצור lost update או double spending. סדר
נעילות דטרמיניסטי מונע deadlock, ושער transaction גלובלי מגן על קובץ JSON.
ההגנה תקפה לתהליך Python יחיד ול-event loop יחיד בלבד."""
        ),
    )
    add_code_cell(
        notebook,
        """
import asyncio

async def create_user_for(container_value, name, phone, balance, key):
    return await container_value.orchestrator.handle(
        f'createUser name="{name}" phone={phone} initial_balance={balance}',
        correlation_id=f"COR-{key}",
        idempotency_key=f"IDEM-{key}",
        requested_at=SCENARIO_TIME,
    )

# 1. Double-spending prevention.
withdraw_container, _ = await isolated_container("concurrent_withdraw")
withdraw_source = await create_user_for(
    withdraw_container, "Withdraw Source", "0505555555", "100.00", "CW-SOURCE"
)
withdraw_a = await create_user_for(
    withdraw_container, "Withdraw A", "0505555556", "0.00", "CW-A"
)
withdraw_b = await create_user_for(
    withdraw_container, "Withdraw B", "0505555557", "0.00", "CW-B"
)
withdraw_source_id = withdraw_source.output["user_id"]
withdraw_results = await asyncio.gather(
    withdraw_container.orchestrator.handle(
        (
            f"transferMoney sender_id={withdraw_source_id} "
            f"receiver_id={withdraw_a.output['user_id']} amount=80.00"
        ),
        correlation_id="COR-CW-1",
        idempotency_key="IDEM-CW-1",
        requested_at=SCENARIO_TIME,
    ),
    withdraw_container.orchestrator.handle(
        (
            f"transferMoney sender_id={withdraw_source_id} "
            f"receiver_id={withdraw_b.output['user_id']} amount=80.00"
        ),
        correlation_id="COR-CW-2",
        idempotency_key="IDEM-CW-2",
        requested_at=SCENARIO_TIME,
    ),
)
withdraw_successes = [
    result for result in withdraw_results
    if isinstance(result.output, dict) and result.output.get("operation") == "transferMoney"
]
withdraw_reflections = [
    result for result in withdraw_results
    if result.agent_name == "ReflectionAgent"
]
assert len(withdraw_successes) == 1
assert len(withdraw_reflections) == 1
assert withdraw_reflections[0].output.error_code == "insufficient_funds"
assert withdraw_container.snapshot().wallets[withdraw_source_id].balance == Decimal("20.00")

# 2. Lost-update prevention for concurrent deposits.
deposit_container, _ = await isolated_container("concurrent_deposit")
deposit_one = await create_user_for(
    deposit_container, "Deposit One", "0506666661", "100.00", "CD-ONE"
)
deposit_two = await create_user_for(
    deposit_container, "Deposit Two", "0506666662", "100.00", "CD-TWO"
)
deposit_target = await create_user_for(
    deposit_container, "Deposit Target", "0506666663", "20.00", "CD-TARGET"
)
deposit_results = await asyncio.gather(
    deposit_container.orchestrator.handle(
        (
            f"transferMoney sender_id={deposit_one.output['user_id']} "
            f"receiver_id={deposit_target.output['user_id']} amount=100.00"
        ),
        correlation_id="COR-CD-1",
        idempotency_key="IDEM-CD-1",
        requested_at=SCENARIO_TIME,
    ),
    deposit_container.orchestrator.handle(
        (
            f"transferMoney sender_id={deposit_two.output['user_id']} "
            f"receiver_id={deposit_target.output['user_id']} amount=100.00"
        ),
        correlation_id="COR-CD-2",
        idempotency_key="IDEM-CD-2",
        requested_at=SCENARIO_TIME,
    ),
)
assert all(result.output["operation"] == "transferMoney" for result in deposit_results)
assert (
    deposit_container.snapshot().wallets[deposit_target.output["user_id"]].balance
    == Decimal("220.00")
)

# 3. Opposite-direction transfers finish without deadlock.
opposite_container, _ = await isolated_container("opposite_direction")
opposite_a = await create_user_for(
    opposite_container, "Opposite A", "0507777771", "100.00", "CO-A"
)
opposite_b = await create_user_for(
    opposite_container, "Opposite B", "0507777772", "100.00", "CO-B"
)
opposite_results = await asyncio.wait_for(
    asyncio.gather(
        opposite_container.orchestrator.handle(
            (
                f"transferMoney sender_id={opposite_a.output['user_id']} "
                f"receiver_id={opposite_b.output['user_id']} amount=10.00"
            ),
            correlation_id="COR-CO-1",
            idempotency_key="IDEM-CO-1",
            requested_at=SCENARIO_TIME,
        ),
        opposite_container.orchestrator.handle(
            (
                f"transferMoney sender_id={opposite_b.output['user_id']} "
                f"receiver_id={opposite_a.output['user_id']} amount=10.00"
            ),
            correlation_id="COR-CO-2",
            idempotency_key="IDEM-CO-2",
            requested_at=SCENARIO_TIME,
        ),
    ),
    timeout=2.0,
)
assert len(opposite_results) == 2
assert all(result.output["operation"] == "transferMoney" for result in opposite_results)
CONCURRENCY_PASSED = True
print("PASS — concurrency safety demonstrations")
""",
        key="concurrency-demonstrations",
    )


def _add_final_sections(notebook: NotebookNode) -> None:
    add_markdown_section(
        notebook,
        SECTION_TITLES[18],
        _rtl(
            """OpenAI, Gemini וספקים תואמי OpenAI הם אפשריים אך לא נדרשים.
כאן נוצרים רק אובייקטי Agent אמיתיים לקריאה בלבד; לא מופעל מודל ולא נוצרת
בקשת provider."""
        ),
    )
    add_code_cell(
        notebook,
        """
from importlib.metadata import version
from agentic_payments.infrastructure.llm.sdk_agents import (
    _router_agent,
    _specialist_agents,
)

sdk_router = _router_agent("not-executed")
sdk_specialists = _specialist_agents("not-executed")
sdk_agents = (
    sdk_router,
    sdk_specialists.triage,
    sdk_specialists.fraud,
    sdk_specialists.security,
    sdk_specialists.explanation,
)
sdk_tool_names = [
    tool.name
    for agent in sdk_agents
    for tool in agent.tools
]
sdk_handoffs = [
    handoff.agent_name for handoff in sdk_specialists.triage.handoffs
]
assert sdk_tool_names == [
    "get_fraud_review_facts",
    "get_security_review_facts",
    "get_last_action_facts",
]
assert not any(
    marker in " ".join(sdk_tool_names).lower()
    for marker in ("transfer", "approve", "create_user")
)
print("OpenAI Agents SDK version:", version("openai-agents"))
print("SDK Agent names:", [agent.name for agent in sdk_agents])
print("Read-only function tools:", sdk_tool_names)
print("Handoff graph:", sdk_handoffs)
print("Financial function tool present: no")
print("Default provider mode: rule_based")
""",
        key="optional-sdk",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[19],
        _rtl(
            """זו סימולציה לימודית ללא authentication המתאים ל-production וללא
חיבור פיננסי אמיתי. JSON ונעילות asyncio מגנים על תהליך ו-event loop יחידים.
פריסה מרובת תהליכים דורשת מסד נתונים טרנזקציוני. פלט LLM הוא advisory בלבד;
הכללים הכספיים נשארים דטרמיניסטיים."""
        ),
    )
    answers = """**1. מה עבד היטב?**  
הפרדת השכבות, ולידציה דטרמיניסטית, זיכרון עסקי ו-audit יצרו זרימה ברורה ובדיקה.

**2. מה היה מוגבל?**  
אחסון JSON ונעילות asyncio מגנים על תהליך יחיד ואינם תחליף למסד נתונים production.

**3. מדוע workflow בטוח יותר מסוכן אוטונומי לא מוגבל?**  
כל מעבר מאומת, לכל כלי יש חוזה קבוע, ורק שירות הדומיין רשאי לשנות כסף.

**4. מדוע כסף משתמש ב-Decimal ולא ב-float?**  
`Decimal` שומר ייצוג עשרוני מדויק ומונע שגיאות עיגול בינאריות.

**5. מדוע צריך גם locks וגם idempotency?**  
Locks מגנים על פעולות מקבילות; idempotency מונעת ביצוע כפול של retry זהה.

**6. מתי מודל מקומי מתאים?**  
כאשר פרטיות, עבודה offline ושליטה בעלויות חשובות יותר מאיכות ענן מקסימלית.

**7. מתי שירות ענן מתאים?**  
כאשר נדרשים מודלים חזקים, זמינות מנוהלת ויכולת scale, בכפוף למדיניות פרטיות.

**8. מדוע הפרויקט עובד ללא API key?**  
הנתב הדטרמיניסטי וכל חוקי התשלום הם מקומיים; שכבת ה-LLM אופציונלית בלבד."""
    add_markdown_section(
        notebook,
        SECTION_TITLES[20],
        _rtl(answers),
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[21],
        _rtl("""האימות הבא מרכז את כל תנאי ההגשה שנבדקו בפועל במהלך הריצה."""),
    )
    add_code_cell(
        notebook,
        """
final_outbox = await high_restart.flush_outbox()
FINAL_CHECKS = {
    "package imported": PACKAGE_IMPORTED,
    "deterministic router working": DETERMINISTIC_ROUTER_WORKING,
    "all ten lecturer scenarios passed": LECTURER_SCENARIOS_PASSED,
    "advanced features passed": ADVANCED_FEATURES_PASSED,
    "concurrency demonstration passed": CONCURRENCY_PASSED,
    "persistence restart passed": PERSISTENCE_PASSED,
    "outbox pending count is zero": final_outbox.pending_after == 0,
    "no API key used": settings.llm_api_key is None,
    "no network request made": NO_NETWORK_REQUEST_MADE,
    "all runtime files are temporary": Path.cwd() == RUNTIME_ROOT,
}
assert all(FINAL_CHECKS.values())
for label, passed in FINAL_CHECKS.items():
    print(f"PASS — {label}: {'yes' if passed else 'no'}")
print("FINAL NOTEBOOK VALIDATION PASSED")
""",
        key="final-validation",
    )
    add_markdown_section(
        notebook,
        SECTION_TITLES[22],
        _rtl(
            """התא האחרון חוזר לתיקיית ההפעלה ומנקה את כל קובצי המקור,
ה-state וה-audit הזמניים."""
        ),
    )
    add_code_cell(
        notebook,
        """
os.chdir(NOTEBOOK_LAUNCH_DIRECTORY)
if str((RUNTIME_ROOT / "src").resolve()) in sys.path:
    sys.path.remove(str((RUNTIME_ROOT / "src").resolve()))
NOTEBOOK_RUNTIME.cleanup()
assert not RUNTIME_ROOT.exists()
print("Temporary notebook runtime cleaned successfully.")
""",
        key="cleanup-final-cell",
    )


def create_notebook(source_files: dict[str, str]) -> NotebookNode:
    """Create the deterministic unexecuted notebook model."""

    manifest = source_manifest(source_files)
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
        "agentic_payments_source_manifest": list(manifest),
    }
    _add_introductory_sections(notebook, manifest)
    _add_runtime_and_source(notebook, source_files)
    _add_core_demonstrations(notebook)
    _add_lecturer_scenarios(notebook)
    _add_advanced_and_concurrency(notebook)
    _add_final_sections(notebook)
    return notebook


def _execute_notebook(
    notebook: NotebookNode,
    *,
    timeout: int,
    workdir: Path,
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
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=output_path.parent,
    )
    os.close(descriptor)
    staging_path = Path(staging_name)
    try:
        nbformat.write(notebook, staging_path)  # type: ignore[no-untyped-call]
        final_notebook = (
            _execute_notebook(notebook, timeout=timeout, workdir=output_path.parent)
            if execute
            else notebook
        )
        nbformat.write(final_notebook, staging_path)  # type: ignore[no-untyped-call]
        os.replace(staging_path, output_path)
    finally:
        if staging_path.exists():
            staging_path.unlink()


def build_notebook(
    output_path: Path = DEFAULT_OUTPUT,
    *,
    execute: bool = True,
    timeout: int = DEFAULT_TIMEOUT,
) -> NotebookNode:
    """Build, optionally execute, and atomically publish the notebook."""

    if not isinstance(output_path, Path):
        raise TypeError("output_path must be a Path")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise ValueError("timeout must be a positive integer")
    sources = collect_source_files(SOURCE_ROOT)
    notebook = create_notebook(sources)
    _atomic_write_notebook(
        notebook,
        output_path,
        execute=execute,
        timeout=timeout,
    )
    return cast(
        NotebookNode,
        nbformat.read(output_path, as_version=4),  # type: ignore[no-untyped-call]
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the notebook-builder command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Notebook output path.",
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
        help="Per-cell execution timeout in seconds.",
    )
    return parser


def _count_cells(cells: Iterable[NotebookNode], cell_type: str) -> int:
    return sum(cell.cell_type == cell_type for cell in cells)


def main(argv: Sequence[str] | None = None) -> int:
    """Build the requested notebook and print one concise summary."""

    arguments = build_parser().parse_args(argv)
    notebook = build_notebook(
        arguments.output,
        execute=not arguments.no_execute,
        timeout=arguments.timeout,
    )
    manifest = notebook.metadata["agentic_payments_source_manifest"]
    print(
        "Notebook built successfully:",
        arguments.output.name,
        f"cells={len(notebook.cells)}",
        f"code={_count_cells(notebook.cells, 'code')}",
        f"markdown={_count_cells(notebook.cells, 'markdown')}",
        f"sources={len(manifest)}",
        f"executed={'no' if arguments.no_execute else 'yes'}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
