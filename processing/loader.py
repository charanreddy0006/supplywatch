from __future__ import annotations
import json
import logging
from time import perf_counter
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from geoalchemy2 import Geography

from database.models import BronzeEarthquake, BronzePort, IngestionRun, RecordHistory, SilverEarthquake, SilverPort
from processing.history import canonical_json, content_hash, tracked_record, transition_run

log = logging.getLogger(__name__)


def _stamp(value):
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return dt.astimezone(timezone.utc)


def _valid_coordinates(row):
    lat, lon = float(row["latitude"]), float(row["longitude"])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"Invalid coordinates for {row.get('port_id', row.get('event_id'))}: {lat},{lon}")
    return lat, lon


def _manifest_state(manifest, key):
    return (manifest.get("sources") or {}).get(key) or {}


def load_run(session: Session, raw_dir: Path, processed_dir: Path, run_id: str) -> dict:
    started = perf_counter()
    totals = {"bronze_ports": 0, "bronze_earthquakes": 0, "bronze_duplicates": 0, "new": 0, "updated": 0, "unchanged": 0, "rejected": 0, "records_missing": None}
    files = {}
    for key in ("ports", "earthquakes"):
        raw_matches = list((raw_dir / key).rglob(f"*_{run_id}.json"))
        normalized = list((processed_dir / key).rglob(f"*_{run_id}.json"))
        if raw_matches and normalized:
            files[key] = (raw_matches[0], normalized[0])
    manifest_matches = list((raw_dir / "manifests").rglob(f"ingestion_{run_id}.json"))
    manifest = json.loads(manifest_matches[0].read_text(encoding="utf-8")) if manifest_matches else {}
    sources = {"ports": "OCHA GIS hosted layer: NGA World Port Index (Pub 150)", "earthquakes": "USGS FDSN Event Web Service"}

    for key, source in sources.items():
        entry = _manifest_state(manifest, key)
        has_files = key in files
        rows = json.loads(files[key][1].read_text(encoding="utf-8")) if has_files else []
        raw = json.loads(files[key][0].read_text(encoding="utf-8")) if has_files else {"features": []}
        source_status = entry.get("status", "success" if has_files else "failed")
        completeness = entry.get("snapshot_completeness", "unknown")
        if source_status != "success":
            completeness = "failed"
        run = session.get(IngestionRun, (run_id, source))
        if run is None:
            run = IngestionRun(run_id=run_id, source_name=source, started_at=_stamp(entry.get("started_at") or manifest.get("started_at") or datetime.now(timezone.utc)), status="running", snapshot_completeness=completeness, run_metadata={"manifest": manifest, "source_key": key})
            session.add(run)
            session.flush()
        elif run.status != "running":
            raise ValueError(f"Ingestion run {run_id} for {source} already ended with status {run.status}; create a new source run to preserve the ledger")
        if not has_files:
            transition_run(run, "failed", _stamp(entry.get("completed_at") or manifest.get("completed_at") or datetime.now(timezone.utc)), entry.get("error", "No raw/normalized source files were found"))
            run.snapshot_completeness = "failed"
            run.records_received = int(entry.get("records_retrieved", 0) or 0)
            run.records_rejected = int(entry.get("invalid_records", 0) or 0)
            totals["rejected"] += run.records_rejected
            continue

        bronze_cls = BronzePort if key == "ports" else BronzeEarthquake
        bronze_name = "port" if key == "ports" else "quake"
        for feature in raw.get("features", []):
            props = feature.get("properties") or {}
            rid = props.get("index_no") if key == "ports" else feature.get("id")
            payload_hash = __import__("hashlib").sha256(json.dumps(feature, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
            inserted_id = session.execute(insert(bronze_cls).values(source=source, source_record_id=str(rid) if rid is not None else None, source_payload_hash=payload_hash, raw_payload=feature, ingestion_run_id=run_id).on_conflict_do_nothing(constraint=f"uq_bronze_{bronze_name}_source_record_run").returning(bronze_cls.id)).scalar_one_or_none()
            if inserted_id is None:
                totals["bronze_duplicates"] += 1
            else:
                totals[f"bronze_{key}"] += 1

        model = SilverPort if key == "ports" else SilverEarthquake
        kind = "port" if key == "ports" else "earthquake"
        pk = "port_id" if key == "ports" else "event_id"
        count_new = count_updated = count_same = count_bad = 0
        for row in rows:
            try:
                identity = str(row[pk])
                lat, lon = _valid_coordinates(row)
                record = json.loads(canonical_json(tracked_record(row, kind)))
                fingerprint = content_hash(row, kind)
                observed = _stamp(row["ingested_at"])
                values = dict(record)
                values[pk] = identity
                values["location"] = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326).cast(Geography(geometry_type="POINT", srid=4326))
                values["first_ingested_at"] = observed
                values["last_updated_at"] = observed
                values["content_hash"] = fingerprint
                values["last_seen_run_id"] = run_id
                if kind == "earthquake":
                    values["event_time"] = _stamp(row["event_time"])
                if kind == "port" and row.get("source_updated_at"):
                    values["source_updated_at"] = _stamp(row["source_updated_at"])

                current = session.get(model, identity)
                history = session.execute(select(RecordHistory).where(RecordHistory.source_name == source, RecordHistory.source_record_id == identity, RecordHistory.record_type == kind, RecordHistory.valid_to.is_(None)).with_for_update()).scalar_one_or_none()
                previous_hash = (current.content_hash if current else None) or (history.content_hash if history else None)
                if previous_hash is None:
                    count_new += 1
                    change_type = "initial"
                    session.execute(insert(model).values(**values).on_conflict_do_nothing(index_elements=[pk]))
                    hist = RecordHistory(source_name=source, source_record_id=identity, record_type=kind, content_hash=fingerprint, record_data=record, valid_from=observed, observed_at=observed, ingestion_run_id=run_id, ingestion_source_name=source, change_type=change_type)
                    session.add(hist)
                elif previous_hash != fingerprint:
                    count_updated += 1
                    if history:
                        # Enforce strictly increasing, non-overlapping validity even for same-second observations.
                        history.valid_to = max(observed, history.valid_from.replace(microsecond=history.valid_from.microsecond) + __import__("datetime").timedelta(microseconds=1))
                    session.execute(insert(model).values(**values).on_conflict_do_update(index_elements=[pk], set_={k: v for k, v in values.items() if k != "first_ingested_at"}))
                    session.add(RecordHistory(source_name=source, source_record_id=identity, record_type=kind, content_hash=fingerprint, record_data=record, valid_from=history.valid_to if history else observed, observed_at=observed, ingestion_run_id=run_id, ingestion_source_name=source, change_type="updated"))
                else:
                    count_same += 1
                    session.execute(insert(model).values(**values).on_conflict_do_update(index_elements=[pk], set_={"last_seen_run_id": run_id, "content_hash": fingerprint}))
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                count_bad += 1
                log.warning("Skipping invalid %s record: %s", key, exc)

        transition_run(run, "completed" if source_status == "success" else "failed", _stamp(entry.get("completed_at") or manifest.get("completed_at") or datetime.now(timezone.utc)), entry.get("error"))
        run.snapshot_completeness = completeness if completeness in {"complete", "partial", "failed", "unknown"} else "unknown"
        run.records_received = int(entry.get("records_retrieved", len(raw.get("features", []))) or 0)
        run.records_inserted, run.records_updated, run.records_unchanged = count_new, count_updated, count_same
        run.records_rejected = int(entry.get("invalid_records", 0) or 0) + int(entry.get("duplicates_removed", 0) or 0) + count_bad
        run.run_metadata = {"manifest": manifest, "source_key": key, "normalized_count": len(rows)}
        # Absence is measurable only when the source attests to a complete snapshot.
        run.records_missing = None
        if run.snapshot_completeness == "complete":
            existing_ids = set(session.execute(select(getattr(model, pk)).where(model.source == source)).scalars())
            observed_source_ids = set()
            for feature in raw.get("features", []):
                props = feature.get("properties") or {}
                source_id = props.get("index_no") if key == "ports" else feature.get("id")
                if source_id is not None:
                    observed_source_ids.add(str(source_id))
            run.records_missing = len(existing_ids - observed_source_ids)
            totals["records_missing"] = (totals["records_missing"] or 0) + run.records_missing
        totals["new"] += count_new
        totals["updated"] += count_updated
        totals["unchanged"] += count_same
        totals["rejected"] += run.records_rejected
    session.flush()
    totals["duration_seconds"] = round(perf_counter() - started, 3)
    log.info("load run=%s stats=%s", run_id, totals)
    return totals
