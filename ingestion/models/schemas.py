from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class PortRecord:
    port_id: str
    port_name: str
    country: str | None
    latitude: float
    longitude: float
    source: str
    source_updated_at: str | None
    ingested_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EarthquakeRecord:
    event_id: str
    magnitude: float | None
    magnitude_type: str | None
    place: str | None
    event_time: datetime
    longitude: float
    latitude: float
    depth_km: float | None
    event_url: str | None
    status: str | None
    event_type: str | None
    source: str
    ingested_at: datetime

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["event_time"] = self.event_time.isoformat()
        result["ingested_at"] = self.ingested_at.isoformat()
        return result
