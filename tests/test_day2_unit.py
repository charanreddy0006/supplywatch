import pytest
from database.models import Base, SilverPort, SilverEarthquake
from processing.loader import _valid_coordinates
from processing.spatial_processor import calculate_exposures

def test_day2_schema_has_all_five_tables():
    assert {"bronze_ports", "bronze_earthquakes", "silver_ports", "silver_earthquakes", "port_event_exposure"} <= set(Base.metadata.tables)
    assert {"ingestion_runs", "record_history"} <= set(Base.metadata.tables)

def test_silver_spatial_points_are_geography_4326():
    assert SilverPort.__table__.c.location.type.srid == 4326
    assert SilverPort.__table__.c.location.type.spatial_index
    assert SilverEarthquake.__table__.c.location.type.srid == 4326

@pytest.mark.parametrize("row", [
    {"port_id": "x", "latitude": 90.1, "longitude": 0},
    {"event_id": "x", "latitude": 0, "longitude": -181},
])
def test_reject_invalid_coordinates(row):
    with pytest.raises(ValueError): _valid_coordinates(row)

def test_exposure_thresholds_must_be_positive():
    with pytest.raises(ValueError): calculate_exposures(None, (50, 0, 250))
