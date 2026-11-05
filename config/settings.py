from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    log_level: str = "INFO"
    usgs_base_url: str = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    usgs_days: int = 7
    http_connect_timeout: float = 5.0
    http_read_timeout: float = 45.0
    http_max_retries: int = 3
    raw_data_dir: Path = Path("data/raw")
    ports_url: str = "https://gis.unocha.org/server/rest/services/Hosted/global_world_seaport_index_202511/FeatureServer/0/query"
    database_url: str = "postgresql+psycopg://supplywatch:supplywatch@localhost:5432/supplywatch"
    exposure_thresholds_km: tuple[float, ...] = (50.0, 100.0, 250.0)
    freshness_thresholds_hours: dict[str, float] | None = None
    usgs_supported_magnitude_types: tuple[str, ...] | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        threshold_values = {}
        for item in os.getenv("FRESHNESS_THRESHOLDS_HOURS", "").split(","):
            if item.strip():
                source, hours = item.rsplit("=", 1)
                threshold_values[source.strip()] = float(hours)
        magnitude_types = tuple(x.strip().lower() for x in os.getenv("USGS_SUPPORTED_MAGNITUDE_TYPES", "").split(",") if x.strip())
        return cls(
            environment=os.getenv("SUPPLYWATCH_ENV", "development"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            usgs_base_url=os.getenv("USGS_BASE_URL", cls.usgs_base_url),
            usgs_days=int(os.getenv("USGS_DAYS", "7")),
            http_connect_timeout=float(os.getenv("HTTP_CONNECT_TIMEOUT", "5")),
            http_read_timeout=float(os.getenv("HTTP_READ_TIMEOUT", "45")),
            http_max_retries=int(os.getenv("HTTP_MAX_RETRIES", "3")),
            raw_data_dir=Path(os.getenv("RAW_DATA_DIR", "data/raw")),
            ports_url=os.getenv("PORTS_URL", cls.ports_url),
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            exposure_thresholds_km=tuple(float(x) for x in os.getenv("EXPOSURE_THRESHOLDS_KM", "50,100,250").split(",") if x.strip()),
            freshness_thresholds_hours=threshold_values,
            usgs_supported_magnitude_types=magnitude_types or None,
        )
