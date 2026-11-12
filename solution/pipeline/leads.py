from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .normalize import normalize_header, parse_date, parse_decimal, parse_enum, parse_phone
from .pii import PiiVault
from .schemas import Field, WorkflowSchema


@dataclass
class RowResult:
    values: dict[str, str | None] | None
    reason: str | None = None
    warnings: int = 0


@dataclass
class LeadFileStats:
    rows_total: int = 0
    rows_rejected: int = 0
    duplicates_merged: int = 0
    field_warnings: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"rows_total": self.rows_total, "rows_rejected": self.rows_rejected,
                "duplicates_merged": self.duplicates_merged, "field_warnings": self.field_warnings}


def parse_field(spec: Field, text: str) -> str | None:
    if spec.type == "string":
        return text
    if spec.type == "phone":
        return parse_phone(text)
    if spec.type == "date":
        parsed = parse_date(text)
        return parsed.isoformat() if parsed else None
    if spec.type == "decimal":
        amount = parse_decimal(text)
        return str(amount) if amount is not None else None
    if spec.type == "enum":
        return parse_enum(text, spec.values)
    raise ValueError(f"unsupported field type: {spec.type}")


def parse_lead_row(schema: WorkflowSchema, raw: Mapping[str, str]) -> RowResult:
    """Walk fields in schema order; the first failure is the row's single reason."""
    values: dict[str, str | None] = {}
    warnings = 0
    for spec in schema.fields:
        text = (raw.get(spec.name) or "").strip()
        if not text:
            if spec.required:
                return RowResult(None, f"missing_required:{spec.name}")
            values[spec.name] = None
            continue
        parsed = parse_field(spec, text)
        if parsed is None:
            if spec.type == "phone":
                return RowResult(None, "invalid_phone")
            if spec.required:
                return RowResult(None, f"invalid_value:{spec.name}")
            warnings += 1
            values[spec.name] = None
        else:
            values[spec.name] = parsed
    return RowResult(values, None, warnings)


def _upsert_lead(conn, vault: PiiVault, schema: WorkflowSchema, values, batch_id: str) -> bool:
    """Create the lead or merge into it. True when it was a duplicate merge."""
    phone = values[schema.phone_field.name]
    phone_hash = vault.phone_hash(phone)
    reference_name = schema.reference_field.name

    pii_new: dict[str, str] = {}
    attrs_new: dict[str, str] = {}
    for spec in schema.fields:
        value = values[spec.name]
        if value is None or spec.type == "phone" or spec.reference:
            continue
        (pii_new if spec.pii else attrs_new)[spec.name] = value

    existing = conn.execute(
        "SELECT lead_id, attrs_json, pii_enc FROM leads WHERE workflow_id = ? AND phone_hash = ?",
        (schema.workflow_id, phone_hash)).fetchone()

    if existing is None:
        for spec in schema.fields:
            if spec.default is not None and spec.type != "phone" and not spec.reference:
                (pii_new if spec.pii else attrs_new).setdefault(
                    spec.name, spec.default)
        conn.execute(
            "INSERT INTO leads (workflow_id, phone_hash, phone_last4, external_ref, batch_id,"
            " attrs_json, pii_enc) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (schema.workflow_id, phone_hash, phone[-4:], values[reference_name], batch_id,
             json.dumps(attrs_new, sort_keys=True), vault.encrypt_json(pii_new)))
        return False

    lead_id, attrs_json, pii_enc = existing
    attrs = json.loads(attrs_json)
    # last write wins, non-null only
    attrs.update(attrs_new)
    pii = vault.decrypt_json(pii_enc)
    pii.update(pii_new)
    conn.execute(
        "UPDATE leads SET external_ref = ?, attrs_json = ?, pii_enc = ? WHERE lead_id = ?",
        (values[reference_name], json.dumps(attrs, sort_keys=True), vault.encrypt_json(pii), lead_id))
    return True


def ingest_lead_file(conn, vault: PiiVault, schema: WorkflowSchema, path: Path, drop_name: str) -> LeadFileStats:
    batch_id = path.stem
    stats = LeadFileStats()
    header_map = schema.header_map()

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            return stats

        column_to_field: dict[int, str] = {}
        for index, label in enumerate(header):
            field_name = header_map.get(normalize_header(label))
            if field_name and field_name not in column_to_field.values():
                column_to_field[index] = field_name

        row_number = 0
        for cells in reader:
            if all(not cell.strip() for cell in cells):      # blank row: skipped, not counted
                continue
            row_number += 1
            stats.rows_total += 1
            raw = {name: (cells[i] if i < len(cells) else "")
                   for i, name in column_to_field.items()}
            result = parse_lead_row(schema, raw)
            if result.values is None:
                stats.rows_rejected += 1
                conn.execute(
                    "INSERT INTO lead_rejections (workflow_id, drop_name, batch_id, row_number, reason)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (schema.workflow_id, drop_name, batch_id, row_number, result.reason))
                continue
            stats.field_warnings += result.warnings
            if _upsert_lead(conn, vault, schema, result.values, batch_id):
                stats.duplicates_merged += 1
    return stats
