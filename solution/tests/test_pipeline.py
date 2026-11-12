
import json

from pipeline.db import connect, sync_dispositions
from pipeline.derive import build_model
from pipeline.ingest import ingest_drop
from pipeline.pii import PiiVault
from pipeline.reports import write_reports
from pipeline.schemas import Field, WorkflowSchema


def test_events_link_after_lead_arrives_and_reports_are_idempotent(tmp_path):
    vault = PiiVault(b"test-secret-for-pipeline")
    conn = connect(tmp_path / "test.db")
    sync_dispositions(conn, [])

    schema = WorkflowSchema(
        workflow_id="motor_renewal",
        fields=(
            Field("customer_name", "string", required=True, pii=True),
            Field("phone", "phone", required=True),
            Field("order_id", "string", required=True, reference=True),
        ),
    )
    schemas = {"motor_renewal": schema}

    # Create the first drop containing events only.
    drop_1 = tmp_path / "drop_1"
    events_dir = drop_1 / "events"
    events_dir.mkdir(parents=True)

    phone = "9876543210"

    events = [
        {
            "event_id": "event_1",
            "workflow_id": "motor_renewal",
            "call_id": "call_1",
            "event_type": "call.initiated",
            "occurred_at": "2026-10-14T10:00:00Z",
            "phone": phone,
            "payload": {},
        },
        {
            "event_id": "event_2",
            "workflow_id": "motor_renewal",
            "call_id": "call_1",
            "event_type": "call.connected",
            "occurred_at": "2026-10-14T10:01:00Z",
            "phone": phone,
            "payload": {},
        },
    ]

    event_file = events_dir / "events.jsonl"
    event_file.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    # Ingest events before the corresponding lead.
    ingest_drop(conn, vault, schemas, drop_1)

    model_before = build_model(conn)
    assert model_before.orphan_events == 2

    # Create the second drop containing the lead.
    drop_2 = tmp_path / "drop_2"
    leads_dir = drop_2 / "leads" / "motor_renewal"
    leads_dir.mkdir(parents=True)

    lead_file = leads_dir / "batch_1.csv"
    lead_file.write_text(
        "customer_name,phone,order_id\n"
        "Test Customer,9876543210,ORDER001\n",
        encoding="utf-8",
    )

    # Ingest the lead after its events.
    ingest_drop(conn, vault, schemas, drop_2)

    model_after = build_model(conn)
    assert model_after.orphan_events == 0

    # Verify that both events are now linked to the lead.
    lead_key = next(iter(model_after.leads))
    calls = model_after.calls_by_lead[lead_key]

    assert len(calls) == 1
    assert calls[0].call_id == "call_1"
    assert calls[0].connected is True

    # Generate the first set of reports.
    out_1 = tmp_path / "reports_1"
    write_reports(conn, out_1)

    first_reports = {
        path.name: path.read_bytes()
        for path in out_1.iterdir()
        if path.is_file()
    }

    # Re-ingest both drops. They should be skipped.
    summary_1 = ingest_drop(conn, vault, schemas, drop_1)
    summary_2 = ingest_drop(conn, vault, schemas, drop_2)

    assert summary_1.skipped_files == 1
    assert summary_2.skipped_files == 1

    # Generate reports again.
    out_2 = tmp_path / "reports_2"
    write_reports(conn, out_2)

    second_reports = {
        path.name: path.read_bytes()
        for path in out_2.iterdir()
        if path.is_file()
    }

    # Every report must remain byte-identical.
    assert first_reports == second_reports

    conn.close()
