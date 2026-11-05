"""Pipeline health summaries combining run freshness, quality, quarantine, and history."""
from datetime import datetime, timezone
from sqlalchemy import func, select

from analytics.historical import freshness_report
from config.settings import Settings
from database.models import IngestionRun, QualityExecution, QualityIssue, QuarantinedRecord, RecordHistory, SilverEarthquake, SilverPort

SOURCES=("OCHA GIS hosted layer: NGA World Port Index (Pub 150)","USGS FDSN Event Web Service")


def pipeline_health_report(session, now: datetime | None=None):
    now=now or datetime.now(timezone.utc)
    thresholds=Settings.from_env().freshness_thresholds_hours or {}
    raw=freshness_report(session,thresholds,now)
    by_source={r["source"]:r for r in raw}
    sources=[]
    for source in SOURCES:
        report=by_source.get(source)
        if not report:
            status="UNKNOWN"
            report={"source":source,"latest_successful_at":None,"latest_attempted_at":None,"latest_complete_at":None,"hours_since_success":None,"freshness_threshold_hours":thresholds.get(source),"latest_status":None}
        elif report["latest_status"]=="failed":
            status="FAILED"
        elif report["stale"] is None:
            status="UNKNOWN"
        elif report["stale"]:
            status="STALE"
        else:
            status="FRESH"
        sources.append({**report,"health_status":status})
    latest_execution=session.execute(select(QualityExecution).order_by(QualityExecution.started_at.desc()).limit(1)).scalar_one_or_none()
    open_high=session.execute(select(func.count()).select_from(QualityIssue).where(QualityIssue.status=="OPEN",QualityIssue.severity.in_(["CRITICAL","HIGH"]))).scalar_one()
    open_issues=session.execute(select(func.count()).select_from(QualityIssue).where(QualityIssue.status=="OPEN")).scalar_one()
    quarantine_counts={status:int(count) for status,count in session.execute(select(QuarantinedRecord.status,func.count()).group_by(QuarantinedRecord.status)).all()}
    hashes={"ports":int(session.execute(select(func.count()).select_from(SilverPort).where(SilverPort.content_hash.is_not(None))).scalar_one()),
            "ports_total":int(session.execute(select(func.count()).select_from(SilverPort)).scalar_one()),
            "earthquakes":int(session.execute(select(func.count()).select_from(SilverEarthquake).where(SilverEarthquake.content_hash.is_not(None))).scalar_one()),
            "earthquakes_total":int(session.execute(select(func.count()).select_from(SilverEarthquake)).scalar_one())}
    statuses=[r["health_status"] for r in sources]
    overall="FAILED" if "FAILED" in statuses or open_high else "STALE" if "STALE" in statuses else "UNKNOWN" if "UNKNOWN" in statuses else "FRESH"
    return {"generated_at":now.isoformat(),"health_status":overall,"sources":sources,
        "quality":{"latest_execution_id":latest_execution.execution_id if latest_execution else None,
                   "latest_execution_status":latest_execution.status if latest_execution else None,
                   "latest_execution_at":latest_execution.started_at.isoformat() if latest_execution else None,
                   "open_issue_count":int(open_issues),"open_critical_or_high_count":int(open_high)},
        "quarantine_counts":quarantine_counts,"historical_tracking":{"ports_hashed":hashes["ports"],"ports_total":hashes["ports_total"],
            "earthquakes_hashed":hashes["earthquakes"],"earthquakes_total":hashes["earthquakes_total"],
            "history_versions":int(session.execute(select(func.count()).select_from(RecordHistory)).scalar_one())}}
