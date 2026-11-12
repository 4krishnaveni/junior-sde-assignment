from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

IST = timezone(timedelta(hours=5, minutes=30))

_HEADER_RUNS = re.compile(r"[_\s]+")


def normalize_header(value: str) -> str:
    return _HEADER_RUNS.sub(" ", value.lower().strip())


_NON_DIGITS = re.compile(r"[^0-9]")


def parse_phone(value: object) -> str | None:
    if value is None:
        return None
    digits = _NON_DIGITS.sub("", str(value))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    return None


_MONTHS = {n: i for i, n in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_ISO = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_DMY_SLASH = re.compile(r"([0-9]{2})/([0-9]{2})/([0-9]{4})")
_DMY_DASH = re.compile(r"([0-9]{2})-([0-9]{2})-([0-9]{4})")
_DMON_Y = re.compile(r"([0-9]{2})-([A-Za-z]{3})-([0-9]{4})")


def parse_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    try:
        if m := _ISO.fullmatch(text):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := (_DMY_SLASH.fullmatch(text) or _DMY_DASH.fullmatch(text)):
            return date(int(m[3]), int(m[2]), int(m[1]))
        if m := _DMON_Y.fullmatch(text):
            month = _MONTHS.get(m[2].lower())
            if month is None:
                return None
            return date(int(m[3]), month, int(m[1]))
    except ValueError:
        return None
    return None


_CURRENCY_PREFIX = re.compile(r"(?:₹|rs\.?|inr)\s*", re.IGNORECASE)
_AMOUNT = re.compile(r"[0-9][0-9,]*(?:\.[0-9]+)?")
_TWO_PLACES = Decimal("0.01")


def parse_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if m := _CURRENCY_PREFIX.match(text):
        text = text[m.end():]
    if not _AMOUNT.fullmatch(text):
        return None
    try:
        return Decimal(text.replace(",", "")).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def parse_enum(value: object, allowed) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip().lower()
    return candidate if candidate in {a.lower() for a in allowed} else None


def parse_timestamp(value: object) -> datetime | None:
    """UTC (Z), offset (+05:30) or naive (= IST) -> aware UTC datetime."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return parsed.astimezone(timezone.utc)
