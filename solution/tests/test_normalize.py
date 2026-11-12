
from datetime import timezone

from pipeline.normalize import (
    parse_phone,
    parse_date,
    parse_decimal,
    parse_timestamp,
)


def test_valid_phones():
    assert parse_phone("(+91) 9876543210") == "+919876543210"
    assert parse_phone("91-98765-43210") == "+919876543210"
    assert parse_phone("09876543210") == "+919876543210"


def test_invalid_phones():
    assert parse_phone("022-2345-6789") is None
    assert parse_phone("+1 415 555 0134") is None
    assert parse_phone("N/A") is None


def test_valid_dates():
    from datetime import date
    assert parse_date("12/01/2026") == date(2026, 1, 12)


def test_invalid_dates():
    assert parse_date("31/02/2026") is None


def test_valid_decimals():
    from decimal import Decimal
    assert parse_decimal("₹27,554") == Decimal("27554.00")
    assert parse_decimal("INR 1234.5") == Decimal("1234.50")


def test_invalid_decimals():
    assert parse_decimal("N/A") is None


def test_timestamps():
    utc = parse_timestamp("2026-10-14T12:25:24Z")
    offset = parse_timestamp("2026-10-14T17:55:24+05:30")
    naive = parse_timestamp("2026-10-14T17:55:24")

    assert utc == offset == naive
    assert utc.tzinfo == timezone.utc
