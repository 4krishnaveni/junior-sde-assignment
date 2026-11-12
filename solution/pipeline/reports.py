from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from .derive import BUCKETS, build_model, lead_metrics
from .normalize import IST


def _write_csv(path: Path, header, rows) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    os.replace(tmp, path)


def _write_json(path: Path, payload: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _bool(value: bool) -> str:
    return "true" if value else "false"


def write_reports(conn, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    model = build_model(conn)

    catalogues: dict = {}
    metrics = {}
    for key, lead in model.leads.items():
        cat = catalogues.setdefault(
            lead.workflow_id, {c: i for (wf, c), i in model.catalogue.items() if wf == lead.workflow_id})
        metrics[key] = lead_metrics(model.calls_by_lead.get(key, []), cat)

    # 1. batch_summary.csv
    batches: dict = defaultdict(Counter)
    for key, lead in model.leads.items():
        counter = batches[(lead.workflow_id, lead.batch_id)]
        counter["total_leads"] += 1
        counter[metrics[key].bucket] += 1
    _write_csv(out_dir / "batch_summary.csv",
               ["workflow_id", "batch_id", "total_leads", *BUCKETS],
               [[wf, b, c["total_leads"], *(c[x] for x in BUCKETS)] for (wf, b), c in sorted(batches.items())])

    # 2. daily_overview.csv
    daily: dict = defaultdict(
        lambda: {"calls": 0, "connected": 0, "success": set()})
    for key, calls in model.calls_by_lead.items():
        wf = key[0]
        cat = catalogues[wf]
        for call in calls:
            d = daily[(wf, call.initiated_at.astimezone(IST).date().isoformat())]
            d["calls"] += 1
            d["connected"] += call.connected
            if call.disposition in cat and cat[call.disposition].is_success:
                d["success"].add(key)
    _write_csv(out_dir / "daily_overview.csv",
               ["workflow_id", "date", "total_calls", "connected_calls",
                   "connectivity_rate", "success_leads"],
               [[wf, day, d["calls"], d["connected"], f"{d['connected'] / d['calls']:.4f}", len(d["success"])]
                for (wf, day), d in sorted(daily.items())])

    # 3. lead_report.csv
    lead_rows = []
    for key, lead in model.leads.items():
        m = metrics[key]
        lead_rows.append((lead.workflow_id, lead.external_ref, lead.lead_id, [
            lead.workflow_id, lead.external_ref, lead.batch_id, "+91******" + lead.phone_last4,
            m.bucket, m.total_calls, m.connected_calls,
            m.last_call_at.astimezone(IST).isoformat(
                timespec="seconds") if m.last_call_at else "",
            m.current_disposition or "", _bool(m.ever_success)]))
    lead_rows.sort(key=lambda r: (r[0], r[1], r[2]))
    _write_csv(out_dir / "lead_report.csv",
               ["workflow_id", "external_ref", "batch_id", "phone_masked", "bucket", "total_calls",
                "connected_calls", "last_call_at", "current_disposition", "ever_success"],
               [r[3] for r in lead_rows])

    # 4. rejections.csv (no PII)
    rejections = conn.execute(
        "SELECT workflow_id, batch_id, row_number, reason FROM lead_rejections"
        " ORDER BY workflow_id, batch_id, row_number").fetchall()
    _write_csv(out_dir / "rejections.csv", ["workflow_id", "batch_id", "row_number", "reason"],
               [list(r) for r in rejections])

    # 5. data_quality.json
    totals: Counter = Counter()
    for (stats_json,) in conn.execute("SELECT stats_json FROM source_files"):
        totals.update(json.loads(stats_json))
    by_reason = Counter(r[3] for r in rejections)
    _write_json(out_dir / "data_quality.json", {
        "lead_rows_total": totals["rows_total"],
        "lead_rows_rejected": len(rejections),
        "rejections_by_reason": dict(sorted(by_reason.items())),
        "duplicate_lead_rows_merged": totals["duplicates_merged"],
        "field_warnings": totals["field_warnings"],
        "events_total": totals["events_total"],
        "malformed_events": totals["malformed"],
        "duplicate_events_dropped": totals["duplicates_dropped"],
        "orphan_events": model.orphan_events,
        "unknown_disposition_events": model.unknown_disposition_events,
    })
