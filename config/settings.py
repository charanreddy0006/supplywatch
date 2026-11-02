from dataclasses import dataclass
import os
from pathlib import Path


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

    @classmethod
    def from_env(cls) -> "Settings":
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
        )
