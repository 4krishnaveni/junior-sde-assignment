from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .normalize import parse_phone, parse_timestamp
from .pii import PiiVault

INSERT_EVENT = (
    "INSERT OR IGNORE INTO events (event_id, workflow_id, call_id, event_type,"
    " occurred_at_utc, phone_hash, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)"
)


@dataclass
class EventFileStats:
    events_total: int = 0
    malformed: int = 0
    duplicates_dropped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"events_total": self.events_total, "malformed": self.malformed,
                "duplicates_dropped": self.duplicates_dropped}


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def parse_event_line(line: str, vault: PiiVault):
    """Row for the events table, or None if malformed. The raw phone is hashed here, never stored."""
    try:
        obj = json.loads(line)
    except (ValueError, RecursionError):
        return None
    if not isinstance(obj, dict):
        return None
    event_id = obj.get("event_id")
    if isinstance(event_id, bool) or not isinstance(event_id, (str, int)) or str(event_id) == "":
        return None
    occurred = parse_timestamp(obj.get("occurred_at"))
    if occurred is None:
        return None
    canonical = parse_phone(obj.get("phone")) if obj.get(
        "phone") is not None else None
    payload = obj.get("payload")
    return (
        str(event_id), _text_or_none(obj.get("workflow_id")
                                     ), _text_or_none(obj.get("call_id")),
        _text_or_none(obj.get("event_type")), occurred.isoformat(),
        vault.phone_hash(canonical) if canonical else None,
        json.dumps(payload if isinstance(
            payload, dict) else {}, sort_keys=True),
    )


def ingest_event_file(conn, vault: PiiVault, path: Path) -> EventFileStats:
    stats = EventFileStats()
    with path.open(encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            stats.events_total += 1
            row = parse_event_line(line, vault)
            if row is None:
                stats.malformed += 1
                continue
            # event_id already in the ledger
            if conn.execute(INSERT_EVENT, row).rowcount == 0:
                stats.duplicates_dropped += 1
    return stats
