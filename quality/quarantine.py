"""Persistent quarantine writes and guarded investigation/revalidation workflow."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from database.models import QuarantinedRecord
from processing.history import canonical_json
from quality.validators import validate_record

_SEVERITY = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


def store_quarantine(session: Session, source_name: str, source_record_id: str | None, record_type: str,
                     ingestion_run_id: str | None, ingestion_source_name: str | None, payload: dict, errors: list,
                     severity: str | None = None, validation_layer: str = "source_validation"):
    if not errors:
        raise ValueError("Quarantine requires at least one validation error")
    payload_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    identity_key = f"{source_record_id or 'unknown'}:{payload_hash}"
    max_severity = severity or min((e.severity for e in errors), key=lambda s: _SEVERITY[s])
    codes = [{"code": e.code, "severity": e.severity, "message": e.message, "expected": e.expected, "observed": e.observed, "validation_layer": validation_layer} for e in errors]
    result = session.execute(insert(QuarantinedRecord).values(
        source_name=source_name, source_record_id=str(source_record_id) if source_record_id is not None else None,
        record_type=record_type, ingestion_run_id=ingestion_run_id, ingestion_source_name=ingestion_source_name,
        payload_hash=payload_hash, identity_key=identity_key, original_payload=payload, error_codes=codes,
        severity=max_severity, quarantined_at=datetime.now(timezone.utc), status="QUARANTINED", reprocess_attempts=0,
    ).on_conflict_do_nothing(constraint="uq_quarantine_source_run_identity").returning(QuarantinedRecord.id)).scalar_one_or_none()
    if result is not None:
        return result
    return session.execute(select(QuarantinedRecord.id).where(
        QuarantinedRecord.source_name == source_name,
        QuarantinedRecord.ingestion_run_id == ingestion_run_id,
        QuarantinedRecord.ingestion_source_name == ingestion_source_name,
        QuarantinedRecord.identity_key == identity_key,
    )).scalar_one_or_none()


def transition_quarantine(record: QuarantinedRecord, status: str, now: datetime | None = None, notes: str | None = None):
    allowed = {"QUARANTINED": {"UNDER_REVIEW"}, "UNDER_REVIEW": {"READY_FOR_REPROCESSING"}, "READY_FOR_REPROCESSING": {"RESOLVED"}}
    if status not in allowed.get(record.status, set()):
        raise ValueError(f"Invalid quarantine transition: {record.status} -> {status}")
    if status == "READY_FOR_REPROCESSING":
        validation_payload = {**record.original_payload, "_source": record.source_name}
        errors = validate_record(validation_payload, record.record_type)
        old_codes = {item.get("code") for item in (record.error_codes or [])}
        # Dataset-level duplicate IDs require a new dataset uniqueness check; a row-only recheck cannot clear them.
        if "duplicate_source_id" in old_codes:
            from quality.validators import ValidationError
            errors.append(ValidationError("duplicate_source_id", "HIGH", "Duplicate identifier requires dataset-level revalidation", "unique source ID", record.source_record_id))
        if errors:
            record.status = "UNDER_REVIEW"
            record.reviewed_at = now or datetime.now(timezone.utc)
            record.resolution_notes = notes or "Record still fails validation; reprocessing remains blocked."
            record.reprocess_attempts = (record.reprocess_attempts or 0) + 1
            return False
        record.status = "READY_FOR_REPROCESSING"
        record.reviewed_at = now or datetime.now(timezone.utc)
        record.resolution_notes = notes or "Record passed validation and is ready for an explicit reprocessing step."
        record.reprocess_attempts = (record.reprocess_attempts or 0) + 1
        return True
    record.status = status
    record.reviewed_at = now or datetime.now(timezone.utc)
    if notes:
        record.resolution_notes = notes
    return True


def revalidate_quarantine(session: Session, record_id: int):
    record = session.get(QuarantinedRecord, record_id)
    if record is None:
        raise LookupError(f"Quarantined record {record_id} was not found")
    if record.status == "QUARANTINED":
        transition_quarantine(record, "UNDER_REVIEW")
    if record.status != "UNDER_REVIEW":
        raise ValueError(f"Record {record_id} must be under review before revalidation")
    ready = transition_quarantine(record, "READY_FOR_REPROCESSING")
    return record, ready
