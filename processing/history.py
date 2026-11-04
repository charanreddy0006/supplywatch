"""Canonical content fingerprints and database-backed history queries."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import IngestionRun, RecordHistory


def transition_run(run: IngestionRun, status: str, completed_at: datetime | None = None, error: str | None = None):
    if run.status != "running" or status not in {"completed", "failed"}:
        raise ValueError(f"Invalid ingestion run transition: {run.status} -> {status}")
    run.status = status
    run.completed_at = completed_at
    run.error_message = error

PORT_FIELDS = ("port_id", "port_name", "country", "latitude", "longitude", "source", "source_updated_at")
EARTHQUAKE_FIELDS = ("event_id", "magnitude", "magnitude_type", "place", "event_time", "latitude", "longitude", "depth_km", "event_url", "event_type", "source")


def _canonical(value: Any):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Naive datetimes cannot be hashed")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite numbers cannot be hashed")
        return int(value) if value.is_integer() else value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite numbers cannot be hashed")
        return int(value) if value == value.to_integral_value() else float(value.normalize())
    return value


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(_canonical(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def tracked_record(row: dict[str, Any], record_type: str) -> dict[str, Any]:
    fields = PORT_FIELDS if record_type == "port" else EARTHQUAKE_FIELDS if record_type == "earthquake" else None
    if fields is None:
        raise ValueError(f"Unknown record type: {record_type}")
    return {field: row.get(field) for field in fields}


def content_hash(row: dict[str, Any], record_type: str) -> str:
    return hashlib.sha256(canonical_json(tracked_record(row, record_type)).encode("utf-8")).hexdigest()


def record_history(session: Session, source_name: str, record_id: str, record_type: str):
    return session.execute(select(RecordHistory).where(
        RecordHistory.source_name == source_name,
        RecordHistory.source_record_id == str(record_id),
        RecordHistory.record_type == record_type,
    ).order_by(RecordHistory.valid_from, RecordHistory.id)).scalars().all()


def state_as_of(session: Session, source_name: str, record_id: str, record_type: str, at: datetime):
    if at.tzinfo is None:
        raise ValueError("As-of timestamp must include timezone")
    return session.execute(select(RecordHistory).where(
        RecordHistory.source_name == source_name,
        RecordHistory.source_record_id == str(record_id),
        RecordHistory.record_type == record_type,
        RecordHistory.valid_from <= at,
        (RecordHistory.valid_to.is_(None) | (RecordHistory.valid_to > at)),
    )).scalar_one_or_none()


def changed_during(session: Session, start: datetime, end: datetime):
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise ValueError("Change range requires timezone-aware timestamps and end > start")
    return session.execute(select(RecordHistory).where(RecordHistory.valid_from >= start, RecordHistory.valid_from < end).order_by(RecordHistory.valid_from)).scalars().all()


def run_history(session: Session, source_name: str | None = None):
    stmt = select(IngestionRun).order_by(IngestionRun.started_at.desc())
    if source_name:
        stmt = stmt.where(IngestionRun.source_name == source_name)
    return session.execute(stmt).scalars().all()


def latest_successful_runs(session: Session):
    return session.execute(select(IngestionRun).where(IngestionRun.status == "completed").distinct(IngestionRun.source_name).order_by(IngestionRun.source_name, IngestionRun.completed_at.desc())).scalars().all()


def compare_runs(session: Session, first_run: str, second_run: str):
    return session.execute(select(IngestionRun).where(IngestionRun.run_id.in_([first_run, second_run])).order_by(IngestionRun.source_name, IngestionRun.run_id)).scalars().all()
