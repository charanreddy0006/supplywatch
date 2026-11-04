"""Real PostgreSQL/PostGIS incremental pipeline checks; requires a disposable migrated database."""
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from database.connection import make_engine
from database.models import BronzePort, IngestionRun, RecordHistory, SilverPort
from processing.history import state_as_of
from processing.loader import load_run
from analytics.historical import freshness_report
from scripts.load_database import record_failed_runs

URL = os.getenv("SUPPLYWATCH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="Set SUPPLYWATCH_TEST_DATABASE_URL to run PostgreSQL/PostGIS integration checks")


def _write_run(root: Path, run_id: str, observed: datetime, port_name: str, completeness="unknown"):
    raw, processed = root / "raw", root / "processed"
    stamp = observed.isoformat()
    for source in ("ports", "earthquakes"):
        (raw / source / "2026" / "11").mkdir(parents=True, exist_ok=True)
        (processed / source / "2026" / "11").mkdir(parents=True, exist_ok=True)
    port = {"port_id": "SW_DAY3_INTEGRATION_PORT", "port_name": port_name, "country": "ZZ", "latitude": 1.0, "longitude": 2.0,
            "source": "OCHA GIS hosted layer: NGA World Port Index (Pub 150)", "source_updated_at": None, "ingested_at": stamp}
    quake = {"event_id": "SW_DAY3_INTEGRATION_EVENT", "magnitude": 1.0, "magnitude_type": "ml", "place": "test", "event_time": datetime(2026, 10, 30, tzinfo=timezone.utc).isoformat(),
             "latitude": 1.0, "longitude": 2.0, "depth_km": 3.0, "event_url": "https://example.test/e", "event_type": "earthquake",
             "source": "USGS FDSN Event Web Service", "ingested_at": stamp}
    for source, norm, feature in (("ports", [port], {"type": "Feature", "properties": {"index_no": port["port_id"]}, "geometry": {"type": "Point", "coordinates": [2.0, 1.0]}}),
                                  ("earthquakes", [quake], {"type": "Feature", "id": quake["event_id"], "properties": {"id": quake["event_id"]}, "geometry": {"type": "Point", "coordinates": [2.0, 1.0, 3.0]}})):
        (raw / source / "2026" / "11" / f"{source}_{run_id}.json").write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}), encoding="utf-8")
        (processed / source / "2026" / "11" / f"{source}_{run_id}.json").write_text(json.dumps(norm), encoding="utf-8")
    for source in ("ports", "earthquakes"):
        (raw / source / "2026" / "11" / f"{source}_{run_id}.json").write_text(json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"index_no": "SW_DAY3_INTEGRATION_PORT"} if source == "ports" else {}, "id": "SW_DAY3_INTEGRATION_EVENT"}]}), encoding="utf-8")
    sources = {key: {"status": "success", "started_at": stamp, "completed_at": stamp, "records_retrieved": 1, "records_normalized": 1, "snapshot_completeness": completeness} for key in ("ports", "earthquakes")}
    (raw / "manifests").mkdir(parents=True, exist_ok=True)
    (raw / "manifests" / f"ingestion_{run_id}.json").write_text(json.dumps({"run_id": run_id, "started_at": stamp, "completed_at": stamp, "sources": sources}), encoding="utf-8")
    return raw, processed


def test_incremental_loader_history_and_complete_missing_behavior(tmp_path):
    engine = make_engine(URL)
    connection = engine.connect()
    outer = connection.begin()
    try:
        with Session(bind=connection) as session:
            t0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
            runs = []
            for i, name in enumerate(("First Port", "First Port", "Updated Port", "Updated Again")):
                run_id = f"SW_DAY3_PIPE_{i}"
                raw, processed = _write_run(tmp_path / str(i), run_id, t0 + timedelta(days=i), name)
                result = load_run(session, raw, processed, run_id)
                runs.append(result)
            assert (runs[0]["new"], runs[0]["updated"], runs[0]["unchanged"]) == (2, 0, 0)
            assert (runs[1]["new"], runs[1]["updated"], runs[1]["unchanged"]) == (0, 0, 2)
            assert (runs[2]["new"], runs[2]["updated"], runs[2]["unchanged"]) == (0, 1, 1)
            assert (runs[3]["new"], runs[3]["updated"], runs[3]["unchanged"]) == (0, 1, 1)
            history = session.execute(select(RecordHistory).where(RecordHistory.source_record_id == "SW_DAY3_INTEGRATION_PORT").order_by(RecordHistory.valid_from)).scalars().all()
            assert len(history) == 3 and history[0].valid_to == history[1].valid_from and history[1].valid_to == history[2].valid_from
            assert history[0].record_data["port_name"] == "First Port"
            assert history[1].record_data["port_name"] == "Updated Port"
            assert state_as_of(session, history[0].source_name, history[0].source_record_id, "port", t0 + timedelta(hours=1)).record_data["port_name"] == "First Port"
            assert state_as_of(session, history[0].source_name, history[0].source_record_id, "port", t0 + timedelta(days=2, hours=1)).record_data["port_name"] == "Updated Port"
            assert session.get(SilverPort, "SW_DAY3_INTEGRATION_PORT").port_name == "Updated Again"
            assert session.get(SilverPort, "SW_DAY3_INTEGRATION_PORT").last_seen_run_id == "SW_DAY3_PIPE_3"
            # Complete snapshots permit counting absences, but absence still never deletes current data.
            run_id = "SW_DAY3_PIPE_COMPLETE"
            raw, processed = _write_run(tmp_path / "complete", run_id, t0 + timedelta(days=4), "Updated Again", "complete")
            (raw / "ports" / "2026" / "11" / f"ports_{run_id}.json").write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
            (processed / "ports" / "2026" / "11" / f"ports_{run_id}.json").write_text("[]", encoding="utf-8")
            result = load_run(session, raw, processed, run_id)
            assert result["records_missing"] == 1
            assert session.get(SilverPort, "SW_DAY3_INTEGRATION_PORT") is not None
            assert session.get(SilverPort, "SW_DAY3_INTEGRATION_PORT").last_seen_run_id == "SW_DAY3_PIPE_3"
            assert session.get(IngestionRun, (run_id, "OCHA GIS hosted layer: NGA World Port Index (Pub 150)")).status == "completed"
            for suffix, completeness, status in (("PARTIAL", "partial", "success"), ("FAILED", "failed", "failed"), ("UNKNOWN", "unknown", "success")):
                missing_run = f"SW_DAY3_PIPE_{suffix}"
                missing_raw, missing_processed = _write_run(tmp_path / suffix, missing_run, t0 + timedelta(days=5), "Updated Again", completeness)
                (missing_raw / "ports" / "2026" / "11" / f"ports_{missing_run}.json").write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
                (missing_processed / "ports" / "2026" / "11" / f"ports_{missing_run}.json").write_text("[]", encoding="utf-8")
                manifest_path = missing_raw / "manifests" / f"ingestion_{missing_run}.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["sources"]["ports"]["status"] = status
                manifest["sources"]["ports"]["records_retrieved"] = 0
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                result = load_run(session, missing_raw, missing_processed, missing_run)
                assert result["records_missing"] is None
                assert session.get(SilverPort, "SW_DAY3_INTEGRATION_PORT") is not None
                expected_status = "failed" if status == "failed" else "completed"
                assert session.get(IngestionRun, (missing_run, "OCHA GIS hosted layer: NGA World Port Index (Pub 150)")).status == expected_status
            freshness = {row["source"]: row for row in freshness_report(session, {"OCHA GIS hosted layer: NGA World Port Index (Pub 150)": 1000}, t0 + timedelta(days=6))}
            port_freshness = freshness["OCHA GIS hosted layer: NGA World Port Index (Pub 150)"]
            assert port_freshness["latest_complete_at"] == (t0 + timedelta(days=4)).isoformat()
            assert port_freshness["freshness_threshold_hours"] == 1000
            assert port_freshness["stale"] is False
    finally:
        outer.rollback()
        connection.close()
        engine.dispose()


def test_freshness_distinguishes_failure_success_and_thresholds():
    engine = make_engine(URL)
    connection = engine.connect()
    outer = connection.begin()
    try:
        now = datetime(2026, 11, 4, tzinfo=timezone.utc)
        source = "SW_DAY3_FRESHNESS_SOURCE"
        with Session(bind=connection) as session:
            session.add_all([
                IngestionRun(run_id="SW_DAY3_FRESH_OK", source_name=source, started_at=now - timedelta(hours=3), completed_at=now - timedelta(hours=3), status="completed", snapshot_completeness="unknown"),
                IngestionRun(run_id="SW_DAY3_FRESH_FAIL", source_name=source, started_at=now - timedelta(minutes=1), completed_at=now, status="failed", snapshot_completeness="failed", error_message="fixture"),
                IngestionRun(run_id="SW_DAY3_NO_SUCCESS", source_name="SW_DAY3_FAILED_ONLY", started_at=now - timedelta(minutes=2), completed_at=now, status="failed", snapshot_completeness="failed", error_message="fixture"),
            ])
            session.flush()
            result = {row["source"]: row for row in freshness_report(session, {source: 1}, now)}
            assert result[source]["latest_status"] == "failed"
            assert result[source]["latest_successful_at"] == (now - timedelta(hours=3)).isoformat()
            assert result[source]["stale"] is True
            assert result["SW_DAY3_FAILED_ONLY"]["latest_successful_at"] is None
            assert result["SW_DAY3_FAILED_ONLY"]["stale"] is None
    finally:
        outer.rollback()
        connection.close()
        engine.dispose()


def test_database_failure_rolls_back_silver_and_history_then_records_failed_run(tmp_path):
    engine = make_engine(URL)
    connection = engine.connect()
    outer = connection.begin()
    try:
        with Session(bind=connection) as session:
            observed = datetime(2026, 11, 1, tzinfo=timezone.utc)
            raw, processed = _write_run(tmp_path / "baseline", "SW_DAY3_ROLLBACK_BASE", observed, "Stable before failure")
            load_run(session, raw, processed, "SW_DAY3_ROLLBACK_BASE")
            original_hash = session.get(SilverPort, "SW_DAY3_INTEGRATION_PORT").content_hash
            original_history_count = session.scalar(select(func.count()).select_from(RecordHistory))

            raw, processed = _write_run(tmp_path / "failure", "SW_DAY3_ROLLBACK_FAIL", observed + timedelta(days=1), "Must roll back")
            session.execute(text("""
                CREATE FUNCTION sw_day3_test_fail_update() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'controlled Day 3 integration failure'; END; $$
            """))
            session.execute(text("""
                CREATE TRIGGER sw_day3_test_fail BEFORE UPDATE ON silver_ports
                FOR EACH ROW WHEN (OLD.port_id = 'SW_DAY3_INTEGRATION_PORT')
                EXECUTE FUNCTION sw_day3_test_fail_update()
            """))
            with pytest.raises(Exception, match="controlled Day 3 integration failure"):
                with session.begin_nested():
                    load_run(session, raw, processed, "SW_DAY3_ROLLBACK_FAIL")
            session.execute(text("DROP TRIGGER sw_day3_test_fail ON silver_ports"))
            session.execute(text("DROP FUNCTION sw_day3_test_fail_update()"))
            current = session.get(SilverPort, "SW_DAY3_INTEGRATION_PORT")
            assert current.port_name == "Stable before failure"
            assert current.content_hash == original_hash
            assert session.scalar(select(func.count()).select_from(RecordHistory)) == original_history_count
            assert session.scalar(select(func.count()).select_from(BronzePort).where(BronzePort.ingestion_run_id == "SW_DAY3_ROLLBACK_FAIL")) == 0
            record_failed_runs(session, raw, "SW_DAY3_ROLLBACK_FAIL", RuntimeError("controlled Day 3 integration failure"))
            failed = session.get(IngestionRun, ("SW_DAY3_ROLLBACK_FAIL", "OCHA GIS hosted layer: NGA World Port Index (Pub 150)"))
            assert failed.status == "failed" and "controlled Day 3 integration failure" in failed.error_message
    finally:
        outer.rollback()
        connection.close()
        engine.dispose()
