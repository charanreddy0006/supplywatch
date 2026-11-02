import pytest
from ingestion.extractors.port_extractor import PortExtractor


def feat(ident=1, name="Port", coords=[20, 10], country="IN"):
    return {"type": "Feature", "properties": {"index_no": ident, "port_name": name, "country": country},
            "geometry": {"type": "Point", "coordinates": coords}}


def test_valid_missing_optional_invalid_duplicate():
    ex = PortExtractor(None, "")
    data = {"type": "FeatureCollection", "features": [feat(), feat(1, "Dupe"), feat(2, "Other", [200, 0]), feat(3, country=None)]}
    result = ex.extract(data)
    assert len(result) == 2 and result[1].country is None
    assert ex.duplicates_removed == 1 and ex.invalid_records == 1


def test_empty_and_malformed():
    assert PortExtractor(None, "").extract({"type": "FeatureCollection", "features": []}) == []
    with pytest.raises(ValueError):
        PortExtractor(None, "").extract({})


def test_uses_source_coordinate_attributes_when_geometry_is_missing():
    record = feat(4, "Attribute coordinates")
    record["geometry"] = None
    record["properties"].update(latitude=-20.5, longitude=130.25)
    result = PortExtractor(None, "").extract({"type": "FeatureCollection", "features": [record]})
    assert (result[0].latitude, result[0].longitude) == (-20.5, 130.25)
