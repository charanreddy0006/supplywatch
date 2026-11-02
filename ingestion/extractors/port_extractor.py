from datetime import datetime, timezone
import logging
from typing import Any

from ingestion.clients.http_client import HttpClient
from ingestion.models.schemas import PortRecord

PORTS_SOURCE = "OCHA GIS hosted layer: NGA World Port Index (Pub 150)"


class PortExtractor:
    def __init__(self, client: HttpClient, endpoint: str) -> None:
        self.client, self.endpoint = client, endpoint
        self.invalid_records = self.duplicates_removed = 0
        self.logger = logging.getLogger(__name__)

    def fetch(self) -> dict[str, Any]:
        features: list[dict[str, Any]] = []
        offset = 0
        page_size = 2000
        while True:
            payload = self.client.get_json(self.endpoint, params={"where": "1=1", "outFields": "*",
                "returnGeometry": "true", "outSR": "4326", "f": "geojson",
                "resultOffset": offset, "resultRecordCount": page_size})
            if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
                raise ValueError("ArcGIS query did not return a GeoJSON feature list")
            page = payload["features"]
            features.extend(page)
            if len(page) < page_size:
                break
            offset += len(page)
        return {"type": "FeatureCollection", "features": features}

    def extract(self, payload: dict[str, Any], ingested_at: datetime | None = None) -> list[PortRecord]:
        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
            raise ValueError("Port response must be an ArcGIS GeoJSON FeatureCollection")
        stamp = (ingested_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        records: list[PortRecord] = []
        seen: set[str] = set()
        self.invalid_records = self.duplicates_removed = 0
        for feature in payload["features"]:
            try:
                props = feature.get("properties") or {}
                geometry = feature.get("geometry") or {}
                coords = geometry.get("coordinates")
                port_id = props.get("index_no")
                name = props.get("port_name")
                if port_id is None or not isinstance(name, str) or not name.strip():
                    raise ValueError("missing port id or name")
                # Some WPI records have valid source latitude/longitude attributes
                # while the hosted layer omits their point geometry. Use those
                # explicit source fields; never synthesize coordinates.
                if isinstance(coords, list) and len(coords) >= 2:
                    lon, lat = float(coords[0]), float(coords[1])
                else:
                    lon, lat = float(props["longitude"]), float(props["latitude"])
                if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                    raise ValueError("invalid coordinate range")
                key = str(port_id)
                if key in seen:
                    self.duplicates_removed += 1
                    continue
                records.append(PortRecord(key, name.strip(), props.get("country"), lat, lon,
                    PORTS_SOURCE, None, stamp))
                seen.add(key)
            except (AttributeError, TypeError, ValueError):
                self.invalid_records += 1
        self.logger.info("source=ports normalized=%d invalid=%d duplicates=%d", len(records), self.invalid_records, self.duplicates_removed)
        return records
