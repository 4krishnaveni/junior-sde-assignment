from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from .normalize import normalize_header


@dataclass(frozen=True)
class Field:
    name: str
    type: str
    required: bool = False
    pii: bool = False
    reference: bool = False
    aliases: tuple[str, ...] = ()
    values: tuple[str, ...] = ()
    default: str | None = None


@dataclass(frozen=True)
class WorkflowSchema:
    workflow_id: str
    fields: tuple[Field, ...]

    @property
    def phone_field(self) -> Field:
        return next(f for f in self.fields if f.type == "phone")

    @property
    def reference_field(self) -> Field:
        return next(f for f in self.fields if f.reference)

    def header_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for field in self.fields:
            for label in (field.name, *field.aliases):
                mapping.setdefault(normalize_header(label), field.name)
        return mapping


def load_schemas(directory: Path) -> dict[str, WorkflowSchema]:
    schemas: dict[str, WorkflowSchema] = {}
    for path in sorted(directory.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        fields = tuple(
            Field(
                name=f["name"], type=f["type"],
                required=bool(f.get("required", False)),
                pii=bool(f.get("pii", False)),
                reference=bool(f.get("reference", False)),
                aliases=tuple(f.get("aliases", ())),
                values=tuple(f.get("values", ())),
                default=f.get("default"),
            )
            for f in raw["fields"]
        )
        schema = WorkflowSchema(raw["workflow_id"], fields)
        if sum(f.type == "phone" for f in fields) != 1:
            raise ValueError(
                f"{path.name}: schema needs exactly one phone field")
        if sum(f.reference for f in fields) != 1:
            raise ValueError(
                f"{path.name}: schema needs exactly one reference field")
        schemas[schema.workflow_id] = schema
    if not schemas:
        raise ValueError(f"no workflow schemas found in {directory}")
    return schemas


def load_dispositions(path: Path) -> list[tuple[str, str, int, int]]:
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            rows.append((
                row["workflow_id"].strip(), row["code"].strip(),
                int(row["is_terminal"].strip().lower() == "true"),
                int(row["is_success"].strip().lower() == "true"),
            ))
    return rows
