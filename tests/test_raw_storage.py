import json
from datetime import datetime, timezone

from ingestion.storage.raw_storage import RawStorage


def test_payload_and_unique_filename(tmp_path):
    store = RawStorage(tmp_path / "raw")
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    a = store.write_payload("earthquakes", "run", {"features": []}, stamp)
    b = store.write_payload("earthquakes", "run-2", {"features": []}, stamp)
    assert a != b and json.loads(a.read_text()) == {"features": []}


def test_normalized_and_manifest_counts(tmp_path):
    store = RawStorage(tmp_path / "raw")
    path = store.write_normalized("ports", "run", [{"port_id": "1"}])
    manifest = store.write_manifest("run", {"records_normalized": 1})
    assert len(json.loads(path.read_text())) == 1
    assert json.loads(manifest.read_text())["records_normalized"] == 1
