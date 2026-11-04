from datetime import datetime, timezone, timedelta
import pytest

from database.models import IngestionRun
from processing.history import canonical_json, content_hash, transition_run
from processing.loader import _stamp


def test_canonical_json_orders_keys_and_normalizes_numbers_and_nulls():
    assert canonical_json({"b": 1.0, "a": None}) == canonical_json({"a": None, "b": 1})


def test_hash_is_stable_sha256_and_ignores_ingestion_metadata():
    first = {"port_id": "p", "port_name": "Port", "country": None, "latitude": 1.0, "longitude": 2, "source": "x", "source_updated_at": None, "ingested_at": "old"}
    second = {**first, "ingested_at": "new"}
    assert content_hash(first, "port") == content_hash(second, "port")
    assert len(content_hash(first, "port")) == 64
    assert content_hash({**first, "port_name": "Changed"}, "port") != content_hash(first, "port")


def test_hash_null_and_numeric_representation_consistent():
    base = {"event_id": "e", "magnitude": None, "magnitude_type": None, "place": None, "event_time": datetime(2026, 1, 1, tzinfo=timezone.utc), "latitude": 1, "longitude": 2.0, "depth_km": None, "event_url": None, "event_type": None, "source": "usgs"}
    assert content_hash(base, "earthquake") == content_hash({**base, "latitude": 1.0, "longitude": 2}, "earthquake")


def test_hash_rejects_naive_timestamps():
    with pytest.raises(ValueError, match="Naive datetimes"):
        content_hash({"event_id": "e", "event_time": datetime(2026, 1, 1)}, "earthquake")


def test_stamp_normalizes_offset_to_utc():
    assert _stamp("2026-01-01T05:30:00+05:30") == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_run_status_transition_is_terminal_and_utc():
    run = IngestionRun(run_id="r", source_name="s", started_at=datetime.now(timezone.utc), status="running", snapshot_completeness="unknown")
    completed = datetime.now(timezone.utc) + timedelta(seconds=1)
    transition_run(run, "completed", completed)
    assert run.status == "completed" and run.completed_at == completed
    with pytest.raises(ValueError, match="Invalid ingestion run transition"):
        transition_run(run, "failed", completed)
