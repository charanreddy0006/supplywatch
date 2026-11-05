"""PostgreSQL/PostGIS tests for baseline initialization and persisted quality workflows."""
import json, os, runpy
from datetime import datetime, timezone
from pathlib import Path
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from database.connection import make_engine
from database.models import (BronzeEarthquake, BronzePort, IngestionRun, PortEventExposure, QualityExecution,
    QualityIssue, QualityRuleResult, QuarantinedRecord, RecordHistory, SilverEarthquake, SilverPort)
from processing.baseline import initialize_baseline
from processing.history import content_hash
from quality.engine import run_quality_checks
from quality.metrics import quality_scorecards
from quality.quarantine import revalidate_quarantine
from quality.reporting import pipeline_health_report
from processing.loader import load_run

URL=os.getenv("SUPPLYWATCH_TEST_DATABASE_URL")
pytestmark=pytest.mark.skipif(not URL,reason="Set SUPPLYWATCH_TEST_DATABASE_URL to run PostgreSQL/PostGIS integration checks")


def test_baseline_is_idempotent_and_quality_audit_persists():
    engine=make_engine(URL); connection=engine.connect(); outer=connection.begin()
    try:
        with Session(bind=connection) as session:
            stamp=datetime(2026,10,1,tzinfo=timezone.utc)
            first=datetime(2026,9,1,tzinfo=timezone.utc)
            port_source="OCHA GIS hosted layer: NGA World Port Index (Pub 150)"
            quake_source="USGS FDSN Event Web Service"
            session.execute(text("""insert into silver_ports(port_id,port_name,country,latitude,longitude,location,source,first_ingested_at,last_updated_at)
                values('SW_DAY4_BASE_PORT','Baseline Port','ZZ',1,2,ST_SetSRID(ST_MakePoint(2,1),4326)::geography,:source,:first,:first)"""),{"source":port_source,"first":first})
            session.execute(text("""insert into silver_earthquakes(event_id,magnitude,magnitude_type,place,event_time,latitude,longitude,depth_km,event_url,event_type,location,source,first_ingested_at,last_updated_at)
                values('SW_DAY4_BASE_EVENT',null,'ml','Baseline event',:event,1,2,-1,null,'earthquake',ST_SetSRID(ST_MakePoint(2,1),4326)::geography,:source,:first,:first)"""),{"event":first,"source":quake_source,"first":first})
            session.add(BronzePort(source=port_source,source_record_id="SW_DAY4_BASE_PORT",source_payload_hash="a"*64,
                raw_payload={"type":"Feature","properties":{"index_no":"SW_DAY4_BASE_PORT","port_name":"Baseline Port"},"geometry":{"type":"Point","coordinates":[2,1]}},ingestion_run_id="SW_DAY4_BRONZE_RUN"))
            session.add(BronzeEarthquake(source=quake_source,source_record_id="SW_DAY4_BASE_EVENT",source_payload_hash="b"*64,
                raw_payload={"type":"Feature","id":"SW_DAY4_BASE_EVENT","properties":{"mag":None,"magType":"ml","time":1798761600000},"geometry":{"type":"Point","coordinates":[2,1,-1]}},ingestion_run_id="SW_DAY4_BRONZE_RUN"))
            before_exposure=session.scalar(select(func.count()).select_from(PortEventExposure))
            first_result=initialize_baseline(session,stamp)
            saved_first_ingested=session.get(SilverPort,"SW_DAY4_BASE_PORT").first_ingested_at
            second_result=initialize_baseline(session,datetime(2026,10,2,tzinfo=timezone.utc))
            assert first_result["port"]["history_versions_created"]==1 and first_result["earthquake"]["history_versions_created"]==1
            assert second_result["port"]["history_versions_created"]==0 and second_result["port"]["hashes_populated"]==0
            assert session.get(SilverPort,"SW_DAY4_BASE_PORT").first_ingested_at==saved_first_ingested
            assert session.scalar(select(func.count()).select_from(RecordHistory).where(RecordHistory.record_type=="port"))==1
            assert session.scalar(select(func.count()).select_from(RecordHistory).where(RecordHistory.record_type=="earthquake"))==1
            current_port=session.get(SilverPort,"SW_DAY4_BASE_PORT")
            assert current_port.content_hash==content_hash({"port_id":"SW_DAY4_BASE_PORT","port_name":"Baseline Port","country":"ZZ","latitude":1,"longitude":2,"source":port_source,"source_updated_at":None},"port")
            assert session.scalar(select(func.count()).select_from(PortEventExposure))==before_exposure

            quality=run_quality_checks(session,"all")
            scores=quality_scorecards(session,quality.execution_id)
            assert quality.status=="completed"
            assert session.get(QualityExecution,quality.execution_id).status=="completed"
            assert session.scalar(select(func.count()).select_from(QualityRuleResult).where(QualityRuleResult.execution_id==quality.execution_id))==len(quality.rules)
            assert scores["ports"]["completeness"]["records_evaluated"]>0
            assert scores["earthquakes"]["validity"]["records_evaluated"]>0
            assert scores["earthquakes"]["validity"]["records_excluded"]>=1
            health=pipeline_health_report(session,datetime(2026,10,2,tzinfo=timezone.utc))
            assert health["historical_tracking"]["ports_hashed"]==1
            assert health["historical_tracking"]["earthquakes_hashed"]==1
    finally:
        outer.rollback(); connection.close(); engine.dispose()


def test_invalid_normalized_record_is_quarantined_and_not_loaded(tmp_path):
    engine=make_engine(URL); connection=engine.connect(); outer=connection.begin()
    try:
        with Session(bind=connection) as session:
            write_run=runpy.run_path("tests/test_day3_integration.py")["_write_run"]
            raw,processed=write_run(tmp_path,"SW_DAY4_QUARANTINE_RUN",datetime(2026,11,4,tzinfo=timezone.utc)," ")
            result=load_run(session,raw,processed,"SW_DAY4_QUARANTINE_RUN")
            assert result["rejected"]==1
            assert session.get(SilverPort,"SW_DAY3_INTEGRATION_PORT") is None
            quarantined=session.execute(select(QuarantinedRecord).where(QuarantinedRecord.ingestion_run_id=="SW_DAY4_QUARANTINE_RUN")).scalars().all()
            assert len(quarantined)==1
            record=quarantined[0]
            assert record.original_payload["type"]=="Feature"
            assert "port_name_required" in {item["code"] for item in record.error_codes}
            record,ready=revalidate_quarantine(session,record.id)
            assert not ready and record.status=="UNDER_REVIEW"
    finally:
        outer.rollback(); connection.close(); engine.dispose()
