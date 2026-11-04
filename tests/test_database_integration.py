"""Opt-in integration checks against a disposable PostgreSQL/PostGIS test DB."""
import os
import pytest
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from database.connection import make_engine, verify_database
from database.models import Base
from processing.spatial_processor import calculate_exposures
from analytics.queries import (
    counts, earthquakes_for_port, exposed_ports_by_country, latest_event_by_port,
    nearest_earthquake, ports_within,
)

URL = os.getenv("SUPPLYWATCH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="Set SUPPLYWATCH_TEST_DATABASE_URL to run PostgreSQL/PostGIS integration checks")

def test_postgres_connectivity_and_postgis_extension():
    engine = make_engine(URL)
    try:
        assert verify_database(engine).split()[0].startswith("3.")
    finally:
        engine.dispose()

def test_migrated_tables_and_session_lifecycle():
    engine = make_engine(URL)
    try:
        with engine.connect() as connection:
            names = set(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname=current_schema()")).scalars())
            assert {"bronze_ports", "bronze_earthquakes", "silver_ports", "silver_earthquakes", "port_event_exposure", "alembic_version"} <= names
        with Session(engine) as session:
            assert session.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        engine.dispose()

def test_geography_distance_uses_meters_and_longitude_first():
    engine = make_engine(URL)
    try:
        with engine.connect() as connection:
            meters = connection.execute(text("""
                SELECT ST_Distance(
                  ST_SetSRID(ST_MakePoint(0, 0),4326)::geography,
                  ST_SetSRID(ST_MakePoint(1, 0),4326)::geography)
            """)).scalar_one()
            assert 111000 < meters < 112000
    finally:
        engine.dispose()

def test_real_postgis_exposure_bands_boundaries_and_rerun():
    """Uses a separate test DB and rolls the entire fixture transaction back."""
    engine = make_engine(URL)
    connection = engine.connect()
    outer = connection.begin()
    try:
        with Session(bind=connection) as session:
            now = datetime.now(timezone.utc)
            session.execute(text("""
                INSERT INTO silver_ports
                  (port_id,port_name,country,latitude,longitude,location,source,first_ingested_at,last_updated_at)
                VALUES ('SW_TEST_PORT_DAY2','Integration fixture','ZZ',0,0,
                  ST_SetSRID(ST_MakePoint(0,0),4326)::geography,'test-fixture',:now,:now)
            """), {"now": now})
            distances_km = (20, 49, 50, 50.1, 99.9, 100, 100.1, 249.9, 250, 250.1, 300)
            for i, km in enumerate(distances_km):
                session.execute(text("""
                    INSERT INTO silver_earthquakes
                      (event_id,magnitude,magnitude_type,place,event_time,latitude,longitude,location,source,first_ingested_at,last_updated_at)
                    VALUES (:event_id,2.0,'ml','fixture',:now,
                      ST_Y(ST_Project(ST_SetSRID(ST_MakePoint(0,0),4326)::geography,:meters,radians(90))::geometry),
                      ST_X(ST_Project(ST_SetSRID(ST_MakePoint(0,0),4326)::geography,:meters,radians(90))::geometry),
                      ST_Project(ST_SetSRID(ST_MakePoint(0,0),4326)::geography,:meters,radians(90)),
                      'test-fixture',:now,:now)
                """), {"event_id": f"SW_TEST_EVENT_{i:02d}", "meters": km * 1000, "now": now})

            first = calculate_exposures(session, (50, 100, 250))
            rows = session.execute(text("""
                SELECT event_id,distance_meters,proximity_band FROM port_event_exposure
                WHERE port_id='SW_TEST_PORT_DAY2' ORDER BY event_id
            """)).mappings().all()
            assert first["relationships"] == 9
            assert len(rows) == 9
            by_id = {row["event_id"]: row for row in rows}
            expected_bands = {
                0: "Within 50 km", 1: "Within 50 km", 2: "Within 50 km",
                3: "Within 100 km", 4: "Within 100 km", 5: "Within 100 km",
                6: "Within 250 km", 7: "Within 250 km", 8: "Within 250 km",
            }
            assert {i: by_id[f"SW_TEST_EVENT_{i:02d}"]["proximity_band"] for i in expected_bands} == expected_bands
            assert all(row["distance_meters"] >= 0 for row in rows)
            assert "SW_TEST_EVENT_09" not in by_id and "SW_TEST_EVENT_10" not in by_id

            second = calculate_exposures(session, (50, 100, 250))
            final_count = session.execute(text("SELECT count(*) FROM port_event_exposure WHERE port_id='SW_TEST_PORT_DAY2'")).scalar_one()
            assert second["relationships"] == 9
            assert final_count == 9
            assert session.execute(text("""
                SELECT count(*) FROM port_event_exposure e
                LEFT JOIN silver_ports p USING(port_id)
                LEFT JOIN silver_earthquakes q USING(event_id)
                WHERE e.port_id='SW_TEST_PORT_DAY2' AND (p.port_id IS NULL OR q.event_id IS NULL)
            """)).scalar_one() == 0
            assert ports_within(session, 50) == 1
            assert ports_within(session, 100) == 1
            assert ports_within(session, 250) == 1
            assert nearest_earthquake(session, "SW_TEST_PORT_DAY2")["event_id"] == "SW_TEST_EVENT_00"
            assert len(earthquakes_for_port(session, "SW_TEST_PORT_DAY2")) == 9
            assert len(latest_event_by_port(session)) == 1
            assert any(row["country"] == "ZZ" and row["exposed_ports"] == 1 for row in exposed_ports_by_country(session))
            assert counts(session) == {"ports": 1, "earthquakes": 11, "relationships": 9}
            assert nearest_earthquake(session, "SW_TEST_UNKNOWN") is None
            assert earthquakes_for_port(session, "SW_TEST_UNKNOWN") == []

            with pytest.raises(IntegrityError):
                with session.begin_nested():
                    session.execute(text("""
                        INSERT INTO silver_ports
                          (port_id,port_name,latitude,longitude,location,source,first_ingested_at,last_updated_at)
                        VALUES ('SW_TEST_INVALID_COORD','invalid',91,0,
                          ST_SetSRID(ST_MakePoint(0,91),4326)::geography,'test-fixture',:now,:now)
                    """), {"now": now})
    finally:
        outer.rollback()
        connection.close()
        engine.dispose()
