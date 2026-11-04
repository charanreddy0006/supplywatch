"""Inspect ingestion runs, record history and configured source freshness."""
import argparse
import json
from datetime import datetime
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from config.settings import Settings
from database.connection import make_engine
from processing.history import record_history, run_history, state_as_of, changed_during, compare_runs
from analytics.historical import changes_in_run, discoveries_in_run, freshness_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    runs = sub.add_parser("runs", help="Show ingestion-run history")
    runs.add_argument("--source")
    versions = sub.add_parser("versions", help="Show all versions for a port or earthquake")
    versions.add_argument("record_type", choices=["port", "earthquake"])
    versions.add_argument("record_id")
    asof = sub.add_parser("as-of", help="Retrieve a record version as of an ISO timestamp")
    asof.add_argument("record_type", choices=["port", "earthquake"])
    asof.add_argument("record_id")
    asof.add_argument("timestamp")
    changed = sub.add_parser("changes", help="Show records changed in a half-open time range")
    changed.add_argument("start")
    changed.add_argument("end")
    run_changes = sub.add_parser("run-changes", help="Show updates recorded in an ingestion run")
    run_changes.add_argument("run_id")
    run_changes.add_argument("--source")
    new_run = sub.add_parser("new-in-run", help="Show newly discovered ports or earthquakes in a run")
    new_run.add_argument("run_id")
    new_run.add_argument("--record-type", choices=["port", "earthquake"], default="port")
    compare = sub.add_parser("compare", help="Compare per-source metrics for two run IDs")
    compare.add_argument("first_run")
    compare.add_argument("second_run")
    sub.add_parser("freshness", help="Show latest source freshness and configured thresholds")
    args = parser.parse_args()
    settings = Settings.from_env()
    thresholds = settings.freshness_thresholds_hours or {}
    engine = make_engine()
    try:
        with Session(engine) as session:
            if args.command == "runs":
                rows = run_history(session, args.source)
            elif args.command == "versions":
                from processing.history import record_history
                rows = record_history(session, "OCHA GIS hosted layer: NGA World Port Index (Pub 150)" if args.record_type == "port" else "USGS FDSN Event Web Service", args.record_id, args.record_type)
            elif args.command == "as-of":
                source = "OCHA GIS hosted layer: NGA World Port Index (Pub 150)" if args.record_type == "port" else "USGS FDSN Event Web Service"
                rows = state_as_of(session, source, args.record_id, args.record_type, datetime.fromisoformat(args.timestamp.replace("Z", "+00:00")))
            elif args.command == "changes":
                rows = changed_during(session, datetime.fromisoformat(args.start.replace("Z", "+00:00")), datetime.fromisoformat(args.end.replace("Z", "+00:00")))
            elif args.command == "run-changes":
                rows = changes_in_run(session, args.run_id, args.source)
            elif args.command == "new-in-run":
                rows = discoveries_in_run(session, args.run_id, args.record_type)
            elif args.command == "compare":
                rows = compare_runs(session, args.first_run, args.second_run)
            else:
                rows = freshness_report(session, thresholds)
            def default(obj):
                if hasattr(obj, "__table__"):
                    return {attr.key: getattr(obj, attr.key) for attr in inspect(obj).mapper.column_attrs}
                if hasattr(obj, "isoformat"):
                    return obj.isoformat()
                raise TypeError(type(obj).__name__)
            print(json.dumps(rows, default=default, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
