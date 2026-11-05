"""Reusable source and normalization validators for port and event records."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any


@dataclass(frozen=True)
class ValidationError:
    code: str
    severity: str
    message: str
    expected: str
    observed: Any = None


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _port_values(record: dict):
    if "properties" in record:
        props = record.get("properties") or {}
        coords = (record.get("geometry") or {}).get("coordinates")
        lat = coords[1] if isinstance(coords, list) and len(coords) >= 2 else props.get("latitude")
        lon = coords[0] if isinstance(coords, list) and len(coords) >= 2 else props.get("longitude")
        return {"port_id": props.get("index_no"), "port_name": props.get("port_name"), "latitude": lat,
                "longitude": lon, "source": record.get("_source") or props.get("source")}
    return record


def _earthquake_values(record: dict):
    if "properties" in record and "event_id" not in record:
        props = record.get("properties") or {}
        coords = (record.get("geometry") or {}).get("coordinates")
        return {"event_id": record.get("id"), "magnitude": props.get("mag"), "magnitude_type": props.get("magType"),
                "event_time": datetime.fromtimestamp(props["time"] / 1000, tz=timezone.utc) if isinstance(props.get("time"), (int, float)) else None,
                "longitude": coords[0] if isinstance(coords, list) and len(coords) >= 2 else None,
                "latitude": coords[1] if isinstance(coords, list) and len(coords) >= 2 else None,
                "depth_km": coords[2] if isinstance(coords, list) and len(coords) >= 3 else None,
                "source": record.get("_source") or props.get("source")}
    return record


def validate_port(record: dict) -> list[ValidationError]:
    row = _port_values(record)
    errors = []
    identity = row.get("port_id")
    if identity is None or not str(identity).strip():
        errors.append(ValidationError("port_id_required", "CRITICAL", "Port source identifier is missing", "non-empty stable source ID", identity))
    name = row.get("port_name")
    if not isinstance(name, str) or not name.strip():
        errors.append(ValidationError("port_name_required", "HIGH", "Port name is missing or blank", "non-empty port name", name))
    lat, lon = _number(row.get("latitude")), _number(row.get("longitude"))
    if row.get("latitude") is None or row.get("longitude") is None:
        errors.append(ValidationError("port_coordinates_missing", "HIGH", "Port coordinate pair is incomplete", "both latitude and longitude", {"latitude": row.get("latitude"), "longitude": row.get("longitude")}))
    elif lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        errors.append(ValidationError("port_coordinates_invalid", "HIGH", "Port coordinates are nonnumeric, nonfinite, or outside WGS84 ranges", "latitude [-90,90], longitude [-180,180]", {"latitude": row.get("latitude"), "longitude": row.get("longitude")}))
    source = row.get("source")
    if not isinstance(source, str) or not source.strip():
        errors.append(ValidationError("source_metadata_missing", "MEDIUM", "Source metadata is missing", "non-empty source name", source))
    return errors


def validate_earthquake(record: dict) -> list[ValidationError]:
    row = _earthquake_values(record)
    errors = []
    identity = row.get("event_id")
    if identity is None or not str(identity).strip():
        errors.append(ValidationError("event_id_required", "CRITICAL", "USGS event identifier is missing", "non-empty stable event ID", identity))
    lat, lon = _number(row.get("latitude")), _number(row.get("longitude"))
    if row.get("latitude") is None or row.get("longitude") is None:
        errors.append(ValidationError("event_coordinates_missing", "HIGH", "Earthquake coordinate pair is incomplete", "both latitude and longitude", {"latitude": row.get("latitude"), "longitude": row.get("longitude")}))
    elif lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        errors.append(ValidationError("event_coordinates_invalid", "HIGH", "Earthquake coordinates are nonnumeric, nonfinite, or outside WGS84 ranges", "latitude [-90,90], longitude [-180,180]", {"latitude": row.get("latitude"), "longitude": row.get("longitude")}))
    event_time = row.get("event_time")
    if isinstance(event_time, str):
        try:
            event_time = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
        except ValueError:
            pass
    if not isinstance(event_time, datetime):
        errors.append(ValidationError("event_time_invalid", "HIGH", "Earthquake event timestamp is missing or invalid", "timezone-aware event timestamp", str(event_time) if event_time is not None else None))
    elif event_time.tzinfo is None:
        errors.append(ValidationError("event_time_timezone_missing", "HIGH", "Earthquake event timestamp lacks timezone", "timezone-aware event timestamp", event_time.isoformat()))
    magnitude = row.get("magnitude")
    if magnitude is not None and _number(magnitude) is None:
        errors.append(ValidationError("magnitude_invalid", "MEDIUM", "Magnitude is not a finite number", "finite numeric value or null", magnitude))
    magnitude_type = row.get("magnitude_type")
    if magnitude_type is not None and (not isinstance(magnitude_type, str) or not magnitude_type.strip()):
        errors.append(ValidationError("magnitude_type_invalid", "LOW", "Magnitude type must be a non-empty source code when present", "non-empty string or null", magnitude_type))
    depth = row.get("depth_km")
    if depth is not None and _number(depth) is None:
        errors.append(ValidationError("depth_invalid", "MEDIUM", "Depth is not a finite number", "finite number or null; source sign semantics preserved", depth))
    source = row.get("source")
    if not isinstance(source, str) or not source.strip():
        errors.append(ValidationError("source_metadata_missing", "MEDIUM", "Source metadata is missing", "non-empty source name", source))
    return errors


def validate_record(record: dict, record_type: str) -> list[ValidationError]:
    if record_type == "port":
        return validate_port(record)
    if record_type == "earthquake":
        return validate_earthquake(record)
    raise ValueError(f"Unknown record type: {record_type}")


def validate_records(records: list[dict], record_type: str) -> dict[int, list[ValidationError]]:
    validate = validate_port if record_type == "port" else validate_earthquake if record_type == "earthquake" else None
    if validate is None:
        raise ValueError(f"Unknown record type: {record_type}")
    results = {i: validate(row) for i, row in enumerate(records)}
    seen: set[str] = set()
    id_key = "port_id" if record_type == "port" else "event_id"
    for i, row in enumerate(records):
        identity = row.get(id_key)
        if identity is None:
            continue
        identity = str(identity)
        if identity in seen:
            results[i].append(ValidationError("duplicate_source_id", "HIGH", f"Duplicate {record_type} source identifier in this input", "one record per stable source ID", identity))
        seen.add(identity)
    return results
