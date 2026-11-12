from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import db
from .ingest import SourceChanged, ingest_drop
from .pii import PiiKeyMismatch, PiiVault, load_secret
from .reports import write_reports
from .schemas import load_dispositions, load_schemas

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMAS = REPO_ROOT / "assignment-a-data" / "schemas"


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default="ledger.db",
                        help="SQLite database path (default: ledger.db)")
    common.add_argument("--schemas", type=Path, default=DEFAULT_SCHEMAS,
                        help="directory with workflow schemas")

    parser = argparse.ArgumentParser(
        prog="ledger", description="Interaction ledger & reporting pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", parents=[
                            common], help="ingest one or more drop directories, in order")
    ingest.add_argument("drops", nargs="+", type=Path)
    report = sub.add_parser(
        "report", parents=[common], help="write the five report files")
    report.add_argument("--out", type=Path, required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        conn = db.connect(args.db)
        vault = PiiVault(load_secret(args.db))
        db.verify_key(conn, vault)
        schemas = load_schemas(args.schemas)
        db.sync_dispositions(conn, load_dispositions(
            args.schemas / "dispositions.csv"))

        if args.command == "ingest":
            for drop in args.drops:
                s = ingest_drop(conn, vault, schemas, drop)
                print(f"{drop.resolve().name}: ingested {s.lead_files} lead file(s), "
                      f"{s.event_files} event file(s); skipped {s.skipped_files} already ingested")
        else:
            write_reports(conn, args.out)
            print(f"reports written to {args.out}")
    except (SourceChanged, PiiKeyMismatch, FileNotFoundError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
