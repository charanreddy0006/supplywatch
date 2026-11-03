import json, logging
from sqlalchemy.orm import Session
from config.settings import Settings
from database.connection import make_engine
from processing.spatial_processor import calculate_exposures
from analytics.queries import band_distribution, counts, ports_within

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    engine = make_engine()
    try:
        with Session(engine) as session, session.begin():
            result = calculate_exposures(session, Settings.from_env().exposure_thresholds_km)
        with Session(engine) as session:
            summary = {"exposure": result, "counts": counts(session), "ports_within_km": {str(k): ports_within(session, k) for k in Settings.from_env().exposure_thresholds_km}, "bands": [dict(x) for x in band_distribution(session)]}
            print(json.dumps(summary, default=str, indent=2))
    finally: engine.dispose()
