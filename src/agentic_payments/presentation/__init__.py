"""Public command-line presentation API."""

from agentic_payments.presentation.cli import (
    build_parser,
    main,
    run_demo,
    run_interactive,
)
from agentic_payments.presentation.formatters import (
    format_agent_result,
    format_help,
    format_status,
)

__all__ = [
    "format_agent_result",
    "format_status",
    "format_help",
    "run_interactive",
    "run_demo",
    "build_parser",
    "main",
]
