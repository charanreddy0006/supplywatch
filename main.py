"""SupplyWatch Day 1 ingestion orchestration."""
import logging
from datetime import datetime, timezone
import uuid

from config.settings import Settings
from ingestion.clients.http_client import HttpClient
from ingestion.extractors.earthquake_extractor import EarthquakeExtractor
from ingestion.extractors.port_extractor import PortExtractor
from ingestion.storage.raw_storage import RawStorage


def run_pipeline(settings: Settings | None = None) -> tuple[dict, int]:
    settings = settings or Settings.from_env()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run_id = uuid.uuid4().hex
    logger = logging.LoggerAdapter(logging.getLogger("supplywatch"), {"run_id": run_id})
    logger.info("run started run_id=%s", run_id)
    client = HttpClient(settings.http_connect_timeout, settings.http_read_timeout, settings.http_max_retries)
    storage = RawStorage(settings.raw_data_dir)
    started = datetime.now(timezone.utc)
    sources: dict[str, dict] = {}
    start, end = EarthquakeExtractor.default_range(settings.usgs_days)
    jobs = [
        ("ports", PortExtractor(client, settings.ports_url), None),
        ("earthquakes", EarthquakeExtractor(client, settings.usgs_base_url), (start, end)),
    ]
    for name, extractor, date_range in jobs:
        source_start = datetime.now(timezone.utc)
        entry: dict = {"status": "failed", "started_at": source_start.isoformat(), "records_retrieved": 0,
                       "records_normalized": 0, "invalid_records": 0, "duplicates_removed": 0}
        try:
            payload = extractor.fetch() if date_range is None else extractor.fetch(*date_range)
            entry["records_retrieved"] = len(payload.get("features", []))
            entry["raw_path"] = str(storage.write_payload(name, run_id, payload))
            normalized = extractor.extract(payload)
            entry["normalized_path"] = str(storage.write_normalized(name, run_id, [r.to_dict() for r in normalized]))
            entry["records_normalized"] = len(normalized)
            entry["invalid_records"] = extractor.invalid_records
            entry["duplicates_removed"] = extractor.duplicates_removed
            entry["status"] = "success"
            logger.info("source=%s retrieved=%d normalized=%d invalid=%d duplicates=%d", name,
                        entry["records_retrieved"], entry["records_normalized"], entry["invalid_records"], entry["duplicates_removed"])
        except Exception as exc:  # Keep other source results and expose the failure in the manifest.
            entry["error"] = f"{type(exc).__name__}: {exc}"
            logger.exception("source=%s ingestion failed", name)
        entry["completed_at"] = datetime.now(timezone.utc).isoformat()
        sources[name] = entry
    completed = datetime.now(timezone.utc)
    manifest = {"run_id": run_id, "started_at": started.isoformat(), "completed_at": completed.isoformat(),
                "duration_seconds": round((completed - started).total_seconds(), 3),
                "date_range": {"start": start.isoformat(), "end": end.isoformat()},
                "status": "success" if all(v["status"] == "success" for v in sources.values()) else "partial_failure",
                "sources": sources}
    manifest_path = storage.write_manifest(run_id, manifest)
    print(f"SupplyWatch run {run_id}: {manifest['status']} | " + ", ".join(
        f"{name}={item['records_normalized']} ({item['status']})" for name, item in sources.items()) + f" | manifest={manifest_path}")
    return manifest, 0 if manifest["status"] == "success" else 1


if __name__ == "__main__":
    _, code = run_pipeline()
    raise SystemExit(code)
