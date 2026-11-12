from __future__ import annotations

import sqlite3
from pathlib import Path

from .pii import PiiKeyMismatch, PiiVault

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS dispositions (
    workflow_id TEXT NOT NULL, code TEXT NOT NULL,
    is_terminal INTEGER NOT NULL CHECK (is_terminal IN (0, 1)),
    is_success  INTEGER NOT NULL CHECK (is_success  IN (0, 1)),
    PRIMARY KEY (workflow_id, code)
);

CREATE TABLE IF NOT EXISTS source_files (
    drop_name TEXT NOT NULL, relpath TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('leads', 'events')),
    sha256 TEXT NOT NULL, stats_json TEXT NOT NULL, ingested_at TEXT NOT NULL,
    PRIMARY KEY (drop_name, relpath)
);

CREATE TABLE IF NOT EXISTS leads (
    lead_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id  TEXT NOT NULL,
    phone_hash   TEXT NOT NULL,
    phone_last4  TEXT NOT NULL,
    external_ref TEXT NOT NULL,
    batch_id     TEXT NOT NULL,
    attrs_json   TEXT NOT NULL,
    pii_enc      TEXT NOT NULL,
    UNIQUE (workflow_id, phone_hash)
);

CREATE TABLE IF NOT EXISTS lead_rejections (
    workflow_id TEXT NOT NULL, drop_name TEXT NOT NULL, batch_id TEXT NOT NULL,
    row_number INTEGER NOT NULL, reason TEXT NOT NULL,
    PRIMARY KEY (workflow_id, drop_name, batch_id, row_number)
);

CREATE TABLE IF NOT EXISTS events (
    event_id        TEXT PRIMARY KEY,
    workflow_id     TEXT,
    call_id         TEXT,
    event_type      TEXT,
    occurred_at_utc TEXT NOT NULL,
    phone_hash      TEXT,
    payload_json    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_phone ON events (workflow_id, phone_hash);
CREATE INDEX IF NOT EXISTS idx_events_call  ON events (workflow_id, call_id);

CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events is an append-only ledger'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events is an append-only ledger'); END;
"""


def connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    return conn


def verify_key(conn: sqlite3.Connection, vault: PiiVault) -> None:
    fingerprint = vault.fingerprint()
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'pii_key_fingerprint'").fetchone()
    if row is None:
        with conn:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('pii_key_fingerprint', ?)", (fingerprint,))
    elif row[0] != fingerprint:
        raise PiiKeyMismatch(
            "This database was created with a different PII key. Set AU_PII_KEY to the "
            "original key (or use the original <db>.key file), or start a fresh database."
        )


def sync_dispositions(conn: sqlite3.Connection, rows) -> None:
    with conn:
        conn.execute("DELETE FROM dispositions")
        conn.executemany(
            "INSERT INTO dispositions (workflow_id, code, is_terminal, is_success) VALUES (?, ?, ?, ?)", rows)
