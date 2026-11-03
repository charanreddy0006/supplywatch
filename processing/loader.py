from __future__ import annotations
import json
import logging
import hashlib
from time import perf_counter
from datetime import datetime
from pathlib import Path
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from geoalchemy2 import Geography
from database.models import BronzeEarthquake, BronzePort, SilverEarthquake, SilverPort

log = logging.getLogger(__name__)

def _stamp(value):
    if isinstance(value, datetime): return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

def _valid_coordinates(row):
    lat, lon = float(row["latitude"]), float(row["longitude"])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180): raise ValueError(f"Invalid coordinates for {row.get('port_id', row.get('event_id'))}: {lat},{lon}")
    return lat, lon

def load_run(session: Session, raw_dir: Path, processed_dir: Path, run_id: str) -> dict:
    started = perf_counter()
    stats = {"bronze_ports": 0, "bronze_earthquakes": 0, "bronze_duplicates": 0, "silver_ports_inserted": 0, "silver_ports_updated": 0, "silver_ports_unchanged": 0, "silver_earthquakes_inserted": 0, "silver_earthquakes_updated": 0, "silver_earthquakes_unchanged": 0, "invalid": 0}
    source_files = {}
    normalized_files = {}
    for key, base in (("ports", raw_dir / "ports"), ("earthquakes", raw_dir / "earthquakes")):
        matches = list(base.rglob(f"*_{run_id}.json"))
        if matches: source_files[key] = matches[0]
        matches = list(processed_dir / key for _ in [0])
        candidates = list((processed_dir / key).rglob(f"*_{run_id}.json"))
        if candidates: normalized_files[key] = candidates[0]
    if set(source_files) != {"ports", "earthquakes"} or set(normalized_files) != {"ports", "earthquakes"}:
        raise FileNotFoundError(f"Raw and normalized port/earthquake files for run {run_id} were not all found")
    raw_payloads = {key: json.loads(path.read_text(encoding="utf-8")) for key, path in source_files.items()}
    rows = {key: json.loads(path.read_text(encoding="utf-8")) for key, path in normalized_files.items()}
    manifest_files = list((raw_dir / "manifests").rglob(f"ingestion_{run_id}.json"))
    manifest = json.loads(manifest_files[0].read_text(encoding="utf-8")) if manifest_files else {}
    sources = {"ports": "OCHA GIS hosted layer: NGA World Port Index (Pub 150)", "earthquakes": "USGS FDSN Event Web Service"}
    for key, model in (("ports", BronzePort), ("earthquakes", BronzeEarthquake)):
        features = raw_payloads[key].get("features", [])
        for feature in features:
            props = feature.get("properties") or {}
            rid = props.get("index_no") if key == "ports" else feature.get("id")
            payload_hash = hashlib.sha256(json.dumps(feature, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
            inserted = session.execute(insert(model).values(source=sources[key], source_record_id=str(rid) if rid is not None else None, source_payload_hash=payload_hash, raw_payload=feature, ingestion_run_id=run_id).on_conflict_do_nothing(constraint=f"uq_bronze_{'port' if key == 'ports' else 'quake'}_source_record_run").returning(model.id)).scalar_one_or_none()
            if inserted is None: stats["bronze_duplicates"] += 1
            else: stats[f"bronze_{key}"] += 1
    for key, model, pk in (("ports", SilverPort, "port_id"), ("earthquakes", SilverEarthquake, "event_id")):
        for row in rows[key]:
            try:
                lat, lon = _valid_coordinates(row)
                ingested = _stamp(row["ingested_at"])
                values = {k: row.get(k) for k in ("port_id", "port_name", "country", "latitude", "longitude", "source", "source_updated_at")} if key == "ports" else {k: row.get(k) for k in ("event_id", "magnitude", "magnitude_type", "place", "latitude", "longitude", "depth_km", "event_url", "event_type", "source")}
                identity = row[pk]
                values["location"] = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326).cast(Geography(geometry_type="POINT", srid=4326))
                values["first_ingested_at"] = ingested
                values["last_updated_at"] = ingested
                if key == "earthquakes": values["event_time"] = _stamp(row["event_time"])
                elif row.get("source_updated_at"): values["source_updated_at"] = _stamp(row["source_updated_at"])
                current = session.get(model, identity)
                if current is None:
                    session.execute(insert(model).values(**values).on_conflict_do_nothing(index_elements=[pk]))
                    stats[f"silver_{key}_inserted"] += 1
                else:
                    compare_fields = [c for c in row if c not in ("ingested_at", "status")]
                    changed = False
                    for col in compare_fields:
                        incoming = _stamp(row[col]) if col in ("event_time", "source_updated_at") and row.get(col) else row.get(col)
                        if getattr(current, col) != incoming:
                            changed = True
                            break
                    if changed:
                        values.pop("first_ingested_at")
                        values["last_updated_at"] = datetime.now(ingested.tzinfo)
                        session.execute(insert(model).values(**values).on_conflict_do_update(index_elements=[pk], set_={k: v for k, v in values.items() if k != "first_ingested_at"}))
                        stats[f"silver_{key}_updated"] += 1
                    else: stats[f"silver_{key}_unchanged"] += 1
            except (ValueError, TypeError, KeyError) as exc:
                stats["invalid"] += 1
                log.warning("Skipping invalid %s record: %s", key, exc)
    session.flush()
    stats["duration_seconds"] = round(perf_counter() - started, 3)
    log.info("load run=%s stats=%s", run_id, stats)
    return stats
