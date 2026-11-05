"""Idempotent effective-dated baseline backfill for existing Silver records."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import IngestionRun, RecordHistory, SilverEarthquake, SilverPort
from processing.history import canonical_json, content_hash, tracked_record

BASELINE_RUNS = {
    "port": ("historical-baseline-v1-ports", "OCHA GIS hosted layer: NGA World Port Index (Pub 150)", SilverPort, "port_id"),
    "earthquake": ("historical-baseline-v1-earthquakes", "USGS FDSN Event Web Service", SilverEarthquake, "event_id"),
}


def initialize_baseline(session: Session, baseline_at: datetime | None = None) -> dict:
    """Initialize one backfill version per current Silver row; caller owns transaction."""
    baseline_at = baseline_at or datetime.now(timezone.utc)
    if baseline_at.tzinfo is None:
        raise ValueError("Baseline timestamp must be timezone-aware")
    baseline_at = baseline_at.astimezone(timezone.utc)
    results = {}
    for record_type, (run_id, source, model, key) in BASELINE_RUNS.items():
        rows = session.execute(select(model).order_by(getattr(model, key))).scalars().all()
        prior_run = session.get(IngestionRun, (run_id, source))
        is_new_run = prior_run is None
        if prior_run and prior_run.status != "completed":
            raise ValueError(f"Baseline run {run_id} exists with non-terminal status {prior_run.status}")
        started_at = prior_run.started_at if prior_run else baseline_at
        ids = [str(getattr(row, key)) for row in rows]
        current_versions = {}
        any_versions = set()
        if ids:
            history_rows = session.execute(select(RecordHistory).where(
                RecordHistory.source_name == source,
                RecordHistory.source_record_id.in_(ids),
                RecordHistory.record_type == record_type,
            ).order_by(RecordHistory.valid_from, RecordHistory.id)).scalars().all()
            for version in history_rows:
                any_versions.add(version.source_record_id)
                if version.valid_to is None:
                    if version.source_record_id in current_versions:
                        raise ValueError(f"Multiple current history versions for {record_type} {version.source_record_id}")
                    current_versions[version.source_record_id] = version
        if is_new_run:
            prior_run = IngestionRun(
                run_id=run_id, source_name=source, started_at=started_at, status="running",
                snapshot_completeness="unknown", records_received=len(rows),
                records_inserted=0, records_updated=0, records_unchanged=len(rows), records_rejected=0,
                run_metadata={"run_type": "historical_baseline_backfill", "baseline_at": started_at.isoformat(), "source_first_ingested_at_provenance": "preserved from existing Silver row; not treated as source observation time"},
            )
            session.add(prior_run)
            session.flush()

        created = populated = 0
        missing_first_ingest = 0
        for row in rows:
            identity = str(getattr(row, key))
            business = tracked_record({field: getattr(row, field) for field in (
                "port_id", "port_name", "country", "latitude", "longitude", "source", "source_updated_at"
            )} if record_type == "port" else {
                field: getattr(row, field) for field in (
                    "event_id", "magnitude", "magnitude_type", "place", "event_time", "latitude", "longitude", "depth_km", "event_url", "event_type", "source"
                )
            }, record_type)
            business = json.loads(canonical_json(business))
            computed = content_hash(business, record_type)
            if row.content_hash and row.content_hash != computed:
                raise ValueError(f"Existing Silver hash does not match current {record_type} {identity}; baseline stopped without overwriting it")
            current = current_versions.get(identity)
            if current and current.content_hash != computed:
                raise ValueError(f"Current history hash does not match Silver {record_type} {identity}; baseline stopped")
            if not row.content_hash:
                row.content_hash = computed
                populated += 1
            if not row.last_seen_run_id:
                row.last_seen_run_id = run_id
            if current is None:
                session.add(RecordHistory(
                    source_name=source, source_record_id=identity, record_type=record_type,
                    content_hash=computed, record_data=business, valid_from=started_at,
                    observed_at=started_at, ingestion_run_id=run_id, ingestion_source_name=source,
                    change_type="updated" if identity in any_versions else "initial",
                    observation_provenance="baseline_backfill",
                ))
                created += 1
            if getattr(row, "first_ingested_at", None) is None:
                missing_first_ingest += 1

        prior_run.status = "completed"
        if is_new_run:
            prior_run.completed_at = baseline_at
            prior_run.run_metadata = {**(prior_run.run_metadata or {}),
                "history_versions_created": created,
                "hashes_populated": populated,
                "source_first_ingested_at_present": len(rows) - missing_first_ingest,
                "source_first_ingested_at_missing": missing_first_ingest,
                "source_first_ingested_at_missing_provenance": "baseline timestamp is recorded in record_history.observed_at and observation_provenance; no synthetic first_ingested_at is assigned",
            }
        results[record_type] = {"run_id": run_id, "records_received": len(rows), "hashes_populated": populated,
            "history_versions_created": created, "first_ingested_at_missing": missing_first_ingest,
            "idempotent_replay": created == 0 and populated == 0}
    session.flush()
    return results
