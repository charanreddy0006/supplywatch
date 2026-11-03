"""Opt-in integration checks against a disposable PostgreSQL/PostGIS test DB."""
import os
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from database.connection import make_engine, verify_database
from database.models import Base

URL = os.getenv("SUPPLYWATCH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="Set SUPPLYWATCH_TEST_DATABASE_URL to run PostgreSQL/PostGIS integration checks")

def test_postgres_connectivity_and_postgis_extension():
    engine = make_engine(URL)
    try:
        assert "POSTGIS" in verify_database(engine).upper()
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
