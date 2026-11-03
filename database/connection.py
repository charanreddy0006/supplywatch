import logging
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from config.settings import Settings

log = logging.getLogger(__name__)


def make_engine(url: str | None = None) -> Engine:
    settings = Settings.from_env()
    return create_engine(url or settings.database_url, pool_pre_ping=True, future=True)


def verify_database(engine: Engine) -> str:
    try:
        with engine.connect() as connection:
            version = str(connection.execute(text("SELECT PostGIS_Version()")).scalar_one())
        log.info("database connected; PostGIS version=%s", version)
        return version
    except Exception:
        log.exception("database connection or PostGIS verification failed")
        raise
