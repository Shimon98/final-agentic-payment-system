"""Format, protocol, and uniqueness tests for UUID identifiers."""

import re

import pytest

from agentic_payments.application import IdGenerator
from agentic_payments.infrastructure import UuidIdGenerator


def test_uuid_id_generator_satisfies_protocol() -> None:
    assert isinstance(UuidIdGenerator(), IdGenerator)


@pytest.mark.parametrize(
    ("method_name", "prefix"),
    [
        ("new_user_id", "USR"),
        ("new_transaction_id", "TXN"),
        ("new_payment_request_id", "REQ"),
        ("new_audit_event_id", "AUD"),
        ("new_correlation_id", "COR"),
    ],
)
def test_uuid_identifier_exact_format(method_name: str, prefix: str) -> None:
    generator = UuidIdGenerator()
    value = getattr(generator, method_name)()

    assert re.fullmatch(rf"{prefix}-[0-9a-f]{{32}}", value)
    assert value == value.strip()


def test_uuid_identifier_practical_uniqueness() -> None:
    generator = UuidIdGenerator()
    identifiers = {generator.new_transaction_id() for _ in range(1_000)}
    assert len(identifiers) == 1_000
