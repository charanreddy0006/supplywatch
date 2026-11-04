from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from ingestion.clients.http_client import HttpClient
from ingestion.models.schemas import EarthquakeRecord

USGS_SOURCE = "USGS FDSN Event Web Service"


class EarthquakeExtractor:
    def __init__(self, client: HttpClient, endpoint: str) -> None:
        self.client, self.endpoint = client, endpoint
        self.invalid_records = self.duplicates_removed = 0
        self.snapshot_complete = False
        self.snapshot_completeness = "unknown"
        self.logger = logging.getLogger(__name__)

    def fetch(self, start: datetime, end: datetime) -> dict[str, Any]:
        params = {"format": "geojson", "starttime": start.astimezone(timezone.utc).isoformat(),
                  "endtime": end.astimezone(timezone.utc).isoformat()}
        payload = self.client.get_json(self.endpoint, params=params)
        metadata = payload.get("metadata") if isinstance(payload, dict) else None
        count = metadata.get("count") if isinstance(metadata, dict) else None
        features = payload.get("features") if isinstance(payload, dict) else None
        self.snapshot_complete = isinstance(count, int) and isinstance(features, list) and count == len(features)
        self.snapshot_completeness = "complete" if self.snapshot_complete else ("partial" if isinstance(count, int) and isinstance(features, list) and count > len(features) else "unknown")
        return payload

    def extract(self, payload: dict[str, Any], ingested_at: datetime | None = None) -> list[EarthquakeRecord]:
        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
            raise ValueError("USGS response must be a GeoJSON FeatureCollection with a features list")
        stamp = ingested_at or datetime.now(timezone.utc)
        records: list[EarthquakeRecord] = []
        seen: set[str] = set()
        self.invalid_records = self.duplicates_removed = 0
        for feature in payload["features"]:
            try:
                props = feature.get("properties") or {}
                event_id = feature.get("id")
                coords = (feature.get("geometry") or {}).get("coordinates")
                if not event_id or not isinstance(coords, list) or len(coords) < 3:
                    raise ValueError("missing id or coordinates")
                lon, lat, depth = (self._float_or_none(v) for v in coords[:3])
                event_ms = props.get("time")
                if lon is None or lat is None or not -180 <= lon <= 180 or not -90 <= lat <= 90 or event_ms is None:
                    raise ValueError("invalid coordinates or missing event timestamp")
                if event_id in seen:
                    self.duplicates_removed += 1
                    continue
                event_time = datetime.fromtimestamp(float(event_ms) / 1000, tz=timezone.utc)
                records.append(EarthquakeRecord(str(event_id), self._float_or_none(props.get("mag")),
                    props.get("magType"), props.get("place"), event_time, lon, lat, depth,
                    props.get("url"), props.get("status"), props.get("type"), USGS_SOURCE, stamp))
                seen.add(event_id)
            except (AttributeError, TypeError, ValueError, OverflowError):
                self.invalid_records += 1
        self.logger.info("source=usgs normalized=%d invalid=%d duplicates=%d", len(records), self.invalid_records, self.duplicates_removed)
        return records

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        if value is None:
            return None
        return float(value)

    @staticmethod
    def default_range(days: int = 7, now: datetime | None = None) -> tuple[datetime, datetime]:
        end = now or datetime.now(timezone.utc)
        end = end.astimezone(timezone.utc)
        return end - timedelta(days=days), end
