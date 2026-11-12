from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .events import ingest_event_file
from .leads import ingest_lead_file


class SourceChanged(RuntimeError):
    pass


@dataclass
class IngestSummary:
    lead_files: int = 0
    event_files: int = 0
    skipped_files: int = 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _already_ingested(conn, drop_name: str, relpath: str, sha: str) -> bool:
    row = conn.execute("SELECT sha256 FROM source_files WHERE drop_name = ? AND relpath = ?",
                       (drop_name, relpath)).fetchone()
    if row is None:
        return False
    if row[0] != sha:
        raise SourceChanged(f"{drop_name}/{relpath} was already ingested with different content. "
                            "Use a fresh database for a regenerated dataset.")
    return True


def _record(conn, drop_name, relpath, kind, sha, stats: dict) -> None:
    conn.execute(
        "INSERT INTO source_files (drop_name, relpath, kind, sha256, stats_json, ingested_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (drop_name, relpath, kind, sha, json.dumps(stats, sort_keys=True),
         datetime.now(timezone.utc).isoformat()))


def ingest_drop(conn, vault, schemas, drop_dir: Path) -> IngestSummary:
    """One transaction per file: a crash loses at most one file, and a re-run resumes."""
    drop_dir = drop_dir.resolve()
    if not drop_dir.is_dir():
        raise FileNotFoundError(f"drop directory not found: {drop_dir}")
    drop_name = drop_dir.name
    summary = IngestSummary()

    leads_root = drop_dir / "leads"
    if leads_root.is_dir():
        for workflow_dir in sorted(p for p in leads_root.iterdir() if p.is_dir()):
            schema = schemas.get(workflow_dir.name)
            if schema is None:
                print(
                    f"warning: no schema for workflow '{workflow_dir.name}', skipping", file=sys.stderr)
                continue
            for path in sorted(workflow_dir.glob("*.csv")):
                relpath = path.relative_to(drop_dir).as_posix()
                sha = _sha256(path)
                if _already_ingested(conn, drop_name, relpath, sha):
                    summary.skipped_files += 1
                    continue
                with conn:
                    stats = ingest_lead_file(
                        conn, vault, schema, path, drop_name)
                    _record(conn, drop_name, relpath,
                            "leads", sha, stats.as_dict())
                summary.lead_files += 1

    events_root = drop_dir / "events"
    if events_root.is_dir():
        for path in sorted(events_root.glob("*.jsonl")):
            relpath = path.relative_to(drop_dir).as_posix()
            sha = _sha256(path)
            if _already_ingested(conn, drop_name, relpath, sha):
                summary.skipped_files += 1
                continue
            with conn:
                stats = ingest_event_file(conn, vault, path)
                _record(conn, drop_name, relpath,
                        "events", sha, stats.as_dict())
            summary.event_files += 1
    return summary
