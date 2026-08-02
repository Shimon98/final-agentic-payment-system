"""Safe asynchronous command-line presentation for the payment simulation."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from agentic_payments.bootstrap import ApplicationContainer, Settings, build_application
from agentic_payments.presentation.formatters import (
    format_agent_result,
    format_help,
    format_status,
    to_safe_json_value,
)


class ConsolePort(Protocol):
    """Minimal asynchronous input and synchronous output boundary."""

    async def read_line(
        self,
        prompt: str,
    ) -> str | None:
        """Read one line or return None at EOF."""

    def write_line(
        self,
        text: str,
    ) -> None:
        """Write one complete display value."""


class _TerminalConsole:
    async def read_line(self, prompt: str) -> str | None:
        try:
            return await asyncio.to_thread(input, prompt)
        except EOFError:
            return None

    def write_line(self, text: str) -> None:
        _print_line(text)


def _print_line(text: str) -> None:
    """Write Unicode safely even when a Windows parent process exposes cp1252."""

    try:
        print(text)
    except UnicodeEncodeError:
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is not None:
            sys.stdout.flush()
            buffer.write(text.encode("utf-8") + b"\n")
            buffer.flush()
            return
        print(text.encode("ascii", errors="backslashreplace").decode("ascii"))


def _format_safe(value: object) -> str:
    return json.dumps(
        to_safe_json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )


async def _finish_interactive(
    container: ApplicationContainer,
    console: ConsolePort,
) -> int:
    try:
        await container.flush_outbox()
    except asyncio.CancelledError:
        raise
    except Exception:
        console.write_line("Final audit flush could not be completed safely.")
    console.write_line("Goodbye. / להתראות.")
    return 0


async def run_interactive(
    container: ApplicationContainer,
    *,
    console: ConsolePort | None = None,
) -> int:
    """Run one reusable event-loop session until clean exit or EOF."""

    if not isinstance(container, ApplicationContainer):
        raise TypeError("container must be ApplicationContainer")
    selected_console = console or _TerminalConsole()
    selected_console.write_line("Agentic Payments interactive mode. Type /help for commands.")
    while True:
        try:
            user_input = await selected_console.read_line("> ")
        except asyncio.CancelledError:
            raise
        except Exception:
            selected_console.write_line("Input could not be read safely.")
            return 1
        if user_input is None:
            return await _finish_interactive(container, selected_console)
        text = user_input.strip()
        if not text:
            continue
        if text in {"/exit", "exit", "quit"}:
            return await _finish_interactive(container, selected_console)
        if text == "/help":
            selected_console.write_line(format_help())
            continue
        if text == "/status":
            selected_console.write_line(format_status(container))
            continue
        if text == "/flush":
            try:
                flush_result = await container.flush_outbox()
                selected_console.write_line(_format_safe(flush_result))
            except asyncio.CancelledError:
                raise
            except Exception:
                selected_console.write_line("Audit flush could not be completed safely.")
            continue
        if text == "/reset":
            try:
                confirmation = await selected_console.read_line("Type RESET to confirm: ")
                if confirmation != "RESET":
                    selected_console.write_line("Reset refused.")
                    continue
                await container.reset_state()
                selected_console.write_line("State reset completed safely.")
            except asyncio.CancelledError:
                raise
            except Exception:
                selected_console.write_line("State reset could not be completed safely.")
            continue
        try:
            agent_result = await container.orchestrator.handle(text)
            selected_console.write_line(format_agent_result(agent_result))
        except asyncio.CancelledError:
            raise
        except Exception:
            selected_console.write_line("Request could not be completed safely.")


def _result_identifier(result: object, field_name: str) -> str:
    output = getattr(result, "output", None)
    if not isinstance(output, Mapping):
        raise ValueError("demo result output is not a mapping")
    value = output.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError("demo result identifier is missing")
    return value


async def run_demo() -> int:
    """Run the complete deterministic scenario against temporary files only."""

    try:
        with TemporaryDirectory(prefix="agentic-payments-demo-") as directory:
            temporary_root = Path(directory)
            settings = Settings(  # type: ignore[call-arg]
                _env_file=None,
                app_env="test",
                llm_provider="rule_based",
                enable_llm_router=False,
                state_file=temporary_root / "payment_state.json",
                audit_file=temporary_root / "audit_log.jsonl",
            )
            container = await build_application(settings)
            results = []

            alice = await container.orchestrator.handle(
                'createUser name="Alice Cohen" phone=0501234567 initial_balance=1000.00',
                idempotency_key="DEMO-CREATE-ALICE",
            )
            results.append(alice)
            bob = await container.orchestrator.handle(
                'createUser name="Bob Levi" phone=0509876543 initial_balance=200.00',
                idempotency_key="DEMO-CREATE-BOB",
            )
            results.append(bob)
            alice_id = _result_identifier(alice, "user_id")
            bob_id = _result_identifier(bob, "user_id")

            results.append(await container.orchestrator.handle(f"checkBalance user_id={alice_id}"))
            results.append(await container.orchestrator.handle(f"checkBalance user_id={bob_id}"))
            results.append(
                await container.orchestrator.handle(
                    (f"transferMoney sender_id={alice_id} receiver_id={bob_id} amount=125.00"),
                    idempotency_key="DEMO-TRANSFER-ALICE-BOB",
                )
            )
            results.append(
                await container.orchestrator.handle(f"showTransactions user_id={alice_id}")
            )
            results.append(await container.orchestrator.handle("explainLastAction"))

            for result in results:
                _print_line(format_agent_result(result))

            final_flush = await container.flush_outbox()
            state = container.snapshot()
            valid = (
                state.wallets[alice_id].balance == Decimal("875.00")
                and state.wallets[bob_id].balance == Decimal("325.00")
                and len(state.transactions) == 1
                and final_flush.pending_after == 0
                and not state.pending_audit_events
            )
            if not valid:
                _print_line("Demo verification failed safely.")
                return 1
            _print_line("Demo completed successfully. / ההדגמה הושלמה בהצלחה.")
            return 0
    except asyncio.CancelledError:
        raise
    except Exception:
        _print_line("Demo could not be completed safely.")
        return 1


def build_parser() -> argparse.ArgumentParser:
    """Build the exact supported argparse command tree."""

    parser = argparse.ArgumentParser(
        prog="agentic-payments",
        description="Educational agentic payment simulation",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="Load settings from an explicit env file without changing the environment.",
    )
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("interactive", help="Start the interactive CLI")
    subcommands.add_parser("demo", help="Run the temporary deterministic demo")
    subcommands.add_parser("status", help="Display safe aggregate status")
    subcommands.add_parser("flush", help="Flush pending audit events")
    reset = subcommands.add_parser("reset", help="Reset persisted business state")
    reset.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the non-interactive state reset.",
    )
    parser.set_defaults(command="interactive", yes=False)
    return parser


async def _run_parsed(arguments: argparse.Namespace) -> int:
    if arguments.command == "demo":
        return await run_demo()
    if arguments.command == "reset" and not arguments.yes:
        _print_line("Reset refused: pass --yes to confirm.")
        return 2
    try:
        settings = Settings(_env_file=arguments.env_file)  # type: ignore[call-arg]
        container = await build_application(settings)
        if arguments.command == "interactive":
            return await run_interactive(container)
        if arguments.command == "status":
            _print_line(format_status(container))
            return 0
        if arguments.command == "flush":
            _print_line(_format_safe(await container.flush_outbox()))
            return 0
        if arguments.command == "reset":
            await container.reset_state()
            _print_line("State reset completed safely.")
            return 0
        _print_line("Unsupported command.")
        return 2
    except asyncio.CancelledError:
        raise
    except Exception:
        _print_line("Application could not be started or completed safely.")
        return 1


def main(
    argv: Sequence[str] | None = None,
) -> int:
    """Parse arguments and own the CLI's single event-loop boundary."""

    arguments = build_parser().parse_args(argv)
    try:
        return asyncio.run(_run_parsed(arguments))
    except KeyboardInterrupt:
        _print_line("Interrupted safely.")
        return 130
