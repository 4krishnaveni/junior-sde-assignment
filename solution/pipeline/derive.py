from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Mapping, Sequence

BUCKET_YET_TO_REACH_OUT = "yet_to_reach_out"
BUCKET_COMPLETED = "completed"
BUCKET_TELEPHONY_FAILED = "in_progress_telephony_failed"
BUCKET_DIALED = "in_progress_dialed"
BUCKETS = (BUCKET_YET_TO_REACH_OUT, BUCKET_TELEPHONY_FAILED,
           BUCKET_DIALED, BUCKET_COMPLETED)

LeadKey = tuple[str, str]   # (workflow_id, phone_hash)
CallKey = tuple[str, str]   # (workflow_id, call_id)


@dataclass(frozen=True)
class DispositionInfo:
    is_terminal: bool
    is_success: bool


@dataclass(frozen=True)
class LeadRow:
    lead_id: int
    workflow_id: str
    external_ref: str
    batch_id: str
    phone_last4: str


@dataclass
class CallFacts:
    lead_key: LeadKey | None = None
    initiated_at: datetime | None = None
    connected: bool = False
    telephony_failed: bool = False
    sets: list = field(default_factory=list)         # (time, event_id, code)
    overrides: list = field(default_factory=list)


@dataclass(frozen=True)
class CallSummary:
    call_id: str
    initiated_at: datetime
    connected: bool
    telephony_failed: bool
    disposition: str | None


@dataclass(frozen=True)
class LeadMetrics:
    total_calls: int
    connected_calls: int
    bucket: str
    last_call_at: datetime | None
    current_disposition: str | None
    ever_success: bool


@dataclass
class ReportModel:
    catalogue: dict
    leads: dict
    calls_by_lead: dict
    orphan_events: int
    unknown_disposition_events: int


def effective_disposition(sets: Iterable, overrides: Iterable) -> str | None:
    """Latest override by occurred_at, else latest set. Ties: higher event_id wins."""
    pool = list(overrides) or list(sets)
    if not pool:
        return None
    return max(pool, key=lambda item: (item[0], item[1]))[2]


def compute_bucket(calls: Sequence[CallSummary], catalogue: Mapping[str, DispositionInfo]) -> str:
    if not calls:
        return BUCKET_YET_TO_REACH_OUT
    if any(c.disposition in catalogue and catalogue[c.disposition].is_terminal for c in calls):
        return BUCKET_COMPLETED
    if all(c.telephony_failed for c in calls):
        return BUCKET_TELEPHONY_FAILED
    return BUCKET_DIALED


def lead_metrics(calls: Sequence[CallSummary], catalogue: Mapping[str, DispositionInfo]) -> LeadMetrics:
    ordered = sorted(calls, key=lambda c: (c.initiated_at, c.call_id))
    with_disposition = [c for c in ordered if c.disposition is not None]
    return LeadMetrics(
        total_calls=len(ordered),
        connected_calls=sum(c.connected for c in ordered),
        bucket=compute_bucket(ordered, catalogue),
        last_call_at=ordered[-1].initiated_at if ordered else None,
        current_disposition=with_disposition[-1].disposition if with_disposition else None,
        ever_success=any(
            c.disposition in catalogue and catalogue[c.disposition].is_success for c in ordered),
    )


def _disposition_code(payload_json: str) -> str | None:
    try:
        payload = json.loads(payload_json)
    except ValueError:
        return None
    code = payload.get("disposition_code") if isinstance(
        payload, dict) else None
    return code if isinstance(code, str) else None


def build_model(conn) -> ReportModel:
    catalogue = {
        (wf, code): DispositionInfo(bool(term), bool(succ))
        for wf, code, term, succ in conn.execute(
            "SELECT workflow_id, code, is_terminal, is_success FROM dispositions")
    }
    leads = {
        (wf, phone_hash): LeadRow(lead_id, wf, ref, batch, last4)
        for lead_id, wf, phone_hash, ref, batch, last4 in conn.execute(
            "SELECT lead_id, workflow_id, phone_hash, external_ref, batch_id, phone_last4 FROM leads")
    }

    calls: dict[CallKey, CallFacts] = {}
    orphans = 0
    unknown = 0
    deferred_overrides = []     # linked via call_id once every call is known

    def record_disposition(call, event_id, event_type, occurred, wf, payload) -> None:
        nonlocal unknown
        code = _disposition_code(payload)
        if code is None or (wf, code) not in catalogue:
            unknown += 1
            return
        entry = (datetime.fromisoformat(occurred), event_id, code)
        (call.overrides if event_type ==
         "disposition.override" else call.sets).append(entry)

    for event_id, wf, call_id, event_type, occurred, phone_hash, payload in conn.execute(
        "SELECT event_id, workflow_id, call_id, event_type, occurred_at_utc, phone_hash, payload_json FROM events"
    ):
        if event_type == "disposition.override":
            deferred_overrides.append(
                (event_id, wf, call_id, occurred, phone_hash, payload))
            continue
        lead_key = (wf, phone_hash) if phone_hash is not None and (
            wf, phone_hash) in leads else None
        if lead_key is None:                      # cannot be linked to a valid lead
            orphans += 1
            continue
        if call_id is None:
            continue
        call = calls.setdefault((wf, call_id), CallFacts())
        if event_type == "call.initiated":
            call.lead_key = lead_key
            at = datetime.fromisoformat(occurred)
            call.initiated_at = at if call.initiated_at is None else min(
                call.initiated_at, at)
        elif call.lead_key is None:
            call.lead_key = lead_key
        if event_type == "call.connected":
            call.connected = True
        elif event_type == "call.telephony_failed":
            call.telephony_failed = True
        elif event_type == "disposition.set":
            record_disposition(call, event_id, event_type,
                               occurred, wf, payload)
        elif event_type is not None and event_type.startswith("disposition."):
            unknown += 1

    for event_id, wf, call_id, occurred, phone_hash, payload in deferred_overrides:
        call = calls.get((wf, call_id)) if call_id is not None else None
        linked = call is not None and call.lead_key is not None
        if not linked and phone_hash is not None and (wf, phone_hash) in leads:
            call = calls.setdefault(
                (wf, call_id), CallFacts()) if call_id is not None else None
            linked = call is not None
            if linked and call.lead_key is None:
                call.lead_key = (wf, phone_hash)
        if not linked:
            orphans += 1
            continue
        record_disposition(
            call, event_id, "disposition.override", occurred, wf, payload)

    calls_by_lead: dict[LeadKey, list[CallSummary]] = {}
    for (wf, call_id), facts in calls.items():
        if facts.initiated_at is None or facts.lead_key is None:
            # a call counts only if call.initiated is present and linked
            continue
        summary = CallSummary(call_id, facts.initiated_at, facts.connected, facts.telephony_failed,
                              effective_disposition(facts.sets, facts.overrides))
        calls_by_lead.setdefault(facts.lead_key, []).append(summary)

    return ReportModel(catalogue, leads, calls_by_lead, orphans, unknown)
