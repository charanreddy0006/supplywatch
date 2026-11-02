from datetime import datetime, timezone
import pytest

from ingestion.extractors.earthquake_extractor import EarthquakeExtractor


def feature(event_id="a", coords=[12, 34, 5], props=None):
    return {"type": "Feature", "id": event_id, "geometry": {"type": "Point", "coordinates": coords},
            "properties": props or {"time": 1735689600000, "mag": 4.2}}


def test_normalizes_valid_and_missing_optional_fields():
    ex = EarthquakeExtractor(None, "")
    records = ex.extract({"type": "FeatureCollection", "features": [feature(), feature("b", [-180, -90, None], {"time": 1})]})
    assert len(records) == 2 and records[1].magnitude is None
    assert records[0].event_time.tzinfo == timezone.utc


def test_invalid_and_duplicate_records_are_counted():
    ex = EarthquakeExtractor(None, "")
    records = ex.extract({"type": "FeatureCollection", "features": [feature(), feature(), feature("bad", [181, 0, 2])]})
    assert len(records) == 1 and ex.duplicates_removed == 1 and ex.invalid_records == 1


def test_empty_and_malformed_payloads():
    assert EarthquakeExtractor(None, "").extract({"type": "FeatureCollection", "features": []}) == []
    with pytest.raises(ValueError):
        EarthquakeExtractor(None, "").extract({})
