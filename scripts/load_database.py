import argparse, json, logging
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session
from database.connection import make_engine
from database.models import IngestionRun
from processing.loader import load_run


def record_failed_runs(session: Session, raw_dir: Path, run_id: str, exc: Exception):
    manifest_path = next(iter((raw_dir / "manifests").rglob(f"ingestion_{run_id}.json")), None)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path else {}
    sources = {"ports": "OCHA GIS hosted layer: NGA World Port Index (Pub 150)", "earthquakes": "USGS FDSN Event Web Service"}
    for key, source in sources.items():
        if session.get(IngestionRun, (run_id, source)) is None:
            item = (manifest.get("sources") or {}).get(key, {})
            started = item.get("started_at", manifest.get("started_at", datetime.now(timezone.utc).isoformat()))
            session.add(IngestionRun(run_id=run_id, source_name=source,
                started_at=datetime.fromisoformat(started.replace("Z", "+00:00")),
                completed_at=datetime.now(timezone.utc), status="failed", snapshot_completeness="failed",
                records_received=int(item.get("records_retrieved", 0) or 0),
                records_rejected=int(item.get("invalid_records", 0) or 0), error_message=f"{type(exc).__name__}: {exc}",
                run_metadata={"manifest": manifest, "source_key": key}))

def find_runs(raw_dir: Path, only: str | None):
    manifests = sorted((raw_dir / "manifests").rglob("ingestion_*.json"), key=lambda p: p.stat().st_mtime)
    result = []
    for path in manifests:
        run_id = path.stem.removeprefix("ingestion_")
        if only and run_id != only: continue
        try: data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): continue
        if data.get("status") == "success": result.append((data.get("completed_at", ""), run_id))
    if only and not result: raise ValueError(f"No successful manifest found for run {only}")
    return [max(result)[1]] if result else []

def main():
    parser = argparse.ArgumentParser(description="Load Day 1 raw and normalized files into Bronze and Silver")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--run-id")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    runs = [args.run_id] if args.run_id else find_runs(args.raw_dir, None)
    if not runs: raise SystemExit("No successful Day 1 ingestion manifest found")
    engine = make_engine()
    totals = {}
    try:
        for run_id in runs:
            try:
                with Session(engine) as session, session.begin():
                    stats = load_run(session, args.raw_dir, args.processed_dir, run_id)
            except Exception as exc:
                with Session(engine) as session, session.begin():
                    record_failed_runs(session, args.raw_dir, run_id, exc)
                raise
            totals[run_id] = stats
        print(json.dumps({"runs": totals}, indent=2))
    finally: engine.dispose()

if __name__ == "__main__": main()
