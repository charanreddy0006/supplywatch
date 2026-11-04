"""Database-backed freshness and change summaries."""
from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from database.models import IngestionRun, RecordHistory, SilverEarthquake, SilverPort


def freshness_report(session: Session, thresholds_hours: dict[str, float], now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    rows = session.execute(select(IngestionRun).order_by(IngestionRun.source_name, IngestionRun.started_at)).scalars().all()
    by_source: dict[str, list[IngestionRun]] = {}
    for row in rows:
        by_source.setdefault(row.source_name, []).append(row)
    report = []
    for source, runs in sorted(by_source.items()):
        successful = [r for r in runs if r.status == "completed"]
        complete = [r for r in successful if r.snapshot_completeness == "complete"]
        latest = max(runs, key=lambda r: r.started_at)
        latest_success = max(successful, key=lambda r: r.completed_at or r.started_at) if successful else None
        successful_at = latest_success.completed_at if latest_success else None
        age = (now - successful_at).total_seconds() / 3600 if successful_at else None
        threshold = thresholds_hours.get(source)
        source_event_time = None
        source_update_time = None
        if "USGS" in source:
            source_event_time = session.execute(select(func.max(SilverEarthquake.event_time)).where(SilverEarthquake.source == source)).scalar_one()
        if "World Port Index" in source:
            source_update_time = session.execute(select(func.max(SilverPort.source_updated_at)).where(SilverPort.source == source)).scalar_one()
        report.append({
            "source": source,
            "latest_successful_at": successful_at.isoformat() if successful_at else None,
            "latest_attempted_at": latest.started_at.isoformat(),
            "latest_attempt_completed_at": latest.completed_at.isoformat() if latest.completed_at else None,
            "latest_complete_at": max((r.completed_at or r.started_at for r in complete), default=None).isoformat() if complete else None,
            "latest_source_event_time": source_event_time.isoformat() if source_event_time else None,
            "latest_source_publication_or_update_time": source_update_time.isoformat() if source_update_time else None,
            "hours_since_success": round(age, 2) if age is not None else None,
            "latest_status": latest.status,
            "records_received": latest.records_received,
            "new": latest.records_inserted,
            "updated": latest.records_updated,
            "unchanged": latest.records_unchanged,
            "rejected": latest.records_rejected,
            "missing": latest.records_missing,
            "freshness_threshold_hours": threshold,
            "stale": (age > threshold) if age is not None and threshold is not None else None,
        })
    return report


def changes_in_run(session: Session, run_id: str, source_name: str | None = None):
    stmt = select(RecordHistory).where(RecordHistory.ingestion_run_id == run_id, RecordHistory.change_type == "updated")
    if source_name:
        stmt = stmt.where(RecordHistory.ingestion_source_name == source_name)
    return session.execute(stmt.order_by(RecordHistory.source_name, RecordHistory.source_record_id)).scalars().all()


def discoveries_in_run(session: Session, run_id: str, record_type: str = "port"):
    return session.execute(select(RecordHistory).where(
        RecordHistory.ingestion_run_id == run_id,
        RecordHistory.change_type == "initial",
        RecordHistory.record_type == record_type,
    ).order_by(RecordHistory.source_record_id)).scalars().all()
