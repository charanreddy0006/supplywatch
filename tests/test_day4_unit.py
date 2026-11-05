from datetime import datetime, timezone
import math
import pytest

from database.models import QuarantinedRecord
from quality.validators import validate_earthquake, validate_port, validate_records
from quality.quarantine import transition_quarantine


def test_port_validator_accepts_good_record_and_reports_required_and_coordinates():
    valid={"port_id":"p1","port_name":"Harbor","latitude":1,"longitude":2,"source":"fixture"}
    assert validate_port(valid)==[]
    errors=validate_port({"port_id":"p1","port_name":" ","latitude":91,"longitude":2,"source":"fixture"})
    assert {e.code for e in errors}=={"port_name_required","port_coordinates_invalid"}


def test_earthquake_validator_allows_unknown_and_negative_magnitude():
    record={"event_id":"e1","magnitude":-0.4,"magnitude_type":"ml","event_time":datetime.now(timezone.utc),
            "latitude":1,"longitude":2,"depth_km":-1.0,"source":"USGS"}
    assert validate_earthquake(record)==[]
    assert validate_earthquake({**record,"magnitude":None})==[]


def test_earthquake_validator_rejects_nonfinite_and_naive_event_time():
    record={"event_id":"e1","magnitude":math.nan,"magnitude_type":"ml","event_time":datetime(2026,1,1),
            "latitude":1,"longitude":2,"depth_km":float("inf"),"source":"USGS"}
    assert {e.code for e in validate_earthquake(record)}=={"event_time_timezone_missing","magnitude_invalid","depth_invalid"}


def test_duplicate_source_ids_are_reported_on_later_record():
    rows=[{"port_id":"p","port_name":"P","latitude":0,"longitude":0,"source":"x"}]*2
    assert validate_records(rows,"port")[1][0].code=="duplicate_source_id"


def test_quarantine_ready_transition_requires_successful_revalidation():
    record=QuarantinedRecord(source_name="OCHA",source_record_id="0",record_type="port",status="UNDER_REVIEW",
        original_payload={"type":"Feature","properties":{"index_no":"0","port_name":" "},"geometry":None},
        error_codes=[{"code":"port_name_required"}])
    assert transition_quarantine(record,"READY_FOR_REPROCESSING") is False
    assert record.status=="UNDER_REVIEW"
