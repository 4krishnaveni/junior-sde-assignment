# Submission

> Replace everything in _italics_. Be concise: bullet points are fine. We read every word.

## Candidate
- **Name: Kurra Krishnaveni
- **Assignment chosen: A (Data) 
- **Time spent (honest estimate): 5 hr

## How to run
Run these commands from the repository root.
Windows PowerShell:

# To activate the environments
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# Generate the small synthetic dataset
python assignment-a-data/tools/generate_data.py --seed 42 --scale small --out data

# Ingest both drops
python solution/ledger.py ingest data/drop_1
python solution/ledger.py ingest data/drop_2

# Generate the five reports
python solution/ledger.py report --out reports

# Run tests
pytest -v

## Design
The solution uses Python and SQLite to ingest lead CSV files and call-event JSONL files, maintain an append-only interaction ledger, and generate reports.

The pipeline is organized into modules for schema handling, normalization, PII protection, database access, lead ingestion, event ingestion, derived call and lead states, reporting, and CLI execution.

# Database design:
leads: stores one record per (workflow_id, phone_hash). It includes the external reference, original batch ID, normalized attributes, encrypted PII, and the last four phone digits.

events: stores call events using event_id as the primary key. Events are append-only; database triggers prevent updates and deletes.

source_files: tracks ingested files using the drop name and relative path, along with a SHA-256 hash and ingestion statistics. This supports repeat-ingestion checks.

lead_rejections: records rejected rows and their reasons without storing rejected customer PII.

dispositions: stores the workflow-specific disposition catalogue.

meta: stores metadata such as the PII key fingerprint.

Indexes on workflow/phone and workflow/call ID support event linking and call lookup.

# PII protection: 
The phone number is normalized and used to create a keyed HMAC hash for matching leads with events. The plaintext phone number is not used as the database identity. PII fields are encrypted using Fernet before storage. A key fingerprint is stored in the database to detect use of a different encryption key.

# Event processing and derived state:
Events are retained in the ledger and linked to leads using the workflow and normalized phone number. Events that arrive before their lead are retained so they can be linked when the lead is ingested later.
Call outcomes are derived from event timestamps. A supervisor override takes precedence over dissposition-set events, and the latest applicable override is selected by event time. Lead buckets are derived from the call history and disposition catalogue.

## Decisions & assumptions

| Decision | Why | Alternative considered |
|---|---|---|
| SQLite for persistence | Simple local database suitable for the assignment and its incremental ingestion requirements | PostgreSQL |
| HMAC hash for phone matching | Allows deterministic matching without storing the phone number in plaintext | Plaintext phone lookup |
| Fernet encryption for PII | Protects PII fields stored in the database | Storing only masked values |
| Append-only event ledger | Preserves original events and prevents accidental modification of interaction history | Updating event records |
| Derive orphan status from current data | Events can arrive before their corresponding leads, so an earlier orphan may become linkable later | Permanently discarding orphan events |
| Select effective disposition by event timestamp | Event arrival order may differ from the actual event order | Using database insertion order |
| Keep the first valid lead's batch ID | Follows the assignment's duplicate-merging rule | Moving a duplicate to the latest batch |

## Failure modes considered

- Invalid or missing required lead values: rejected with a reason.
- Invalid optional values: stored as null and counted as field warnings.
- Duplicate lead identities: merged using non-null values from later rows.
- Duplicate event IDs: dropped.
- Malformed event JSON or missing event IDs: counted and skipped.
- Events arriving before their leads: retained and linked when the lead becomes available.
- Unknown disposition codes: counted and ignored for disposition derivation.
- Repeated ingestion: previously ingested files are skipped.
- Incorrect PII key: the stored key fingerprint allows the application to detect a key mismatch.

Not specifically verified:
- Recovery from a forced process termination during ingestion.
- Performance on the large generated dataset.
- Concurrent ingestion by multiple processes.
- Production key rotation and backup/recovery procedures.

## Testing

The automated test suite contains 15 passing tests:

- Phone normalization: valid and invalid phone numbers.
- Date normalization: supported formats and invalid dates.
- Decimal normalization: valid and invalid values.
- Timestamp normalization.
- Effective disposition: override precedence, latest override, and event-time ordering.
- Lead bucket derivation: all four buckets.
- Integration: events arriving before leads, later event linking, and report idempotency.

Additional manual checks:
- Ingested `drop_1` and `drop_2`.
- Re-ran both drops and confirmed previously ingested files were skipped.
- Generated the reports and checked the data-quality summary.
- Ran Python compilation checks.
The large-scale performance test and forced-crash recovery test were not completed.

## Results

For the generated small dataset using seed 42:
| Metric | Result |
|---|---:|
| Lead rows processed | 2,057 |
| Lead rows rejected | 108 |
| Duplicate lead rows merged | 57 |
| Field warnings | 122 |
| Events processed | 8,745 |
| Malformed events | 8 |
| Duplicate events dropped | 237 |
| Orphan events in final state | 462 |
| Unknown disposition events | 18 |
All 15 automated tests passed.
Re-ingestion checks:
- `drop_1`: 4 lead files and 1 event file ingested initially; 5 files skipped on rerun.
- `drop_2`: 2 lead files and 1 event file ingested initially; 3 files skipped on rerun.
Large-scale performance timings were not measured.

## If I had another day

1. Run the solution against the large generated dataset and measure ingestion and reporting performance.
2. Add tests for crash recovery and more event-ordering edge cases.
3. Improve transaction and recovery handling for interrupted ingestion.
4. Add operational logging and clearer error reporting.
5. Document production key management, backup, and restoration procedures.
