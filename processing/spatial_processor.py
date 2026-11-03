from datetime import datetime, timezone
import logging
from time import perf_counter
from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

def calculate_exposures(session: Session, thresholds_km=(50.0, 100.0, 250.0)) -> dict:
    started = perf_counter()
    thresholds = sorted(float(v) for v in thresholds_km)
    if not thresholds or thresholds[0] <= 0: raise ValueError("Distance thresholds must be positive")
    max_m = thresholds[-1] * 1000
    band_case = "CASE " + " ".join(f"WHEN distance_meters <= {v * 1000} THEN 'Within {v:g} km'" for v in thresholds) + " ELSE NULL END"
    now = datetime.now(timezone.utc)
    rows = session.execute(text(f"""
        WITH measured AS (
          SELECT p.port_id, q.event_id,
                 ST_Distance(p.location, q.location) AS distance_meters
          FROM silver_ports p
          JOIN silver_earthquakes q
            ON ST_DWithin(p.location, q.location, :max_meters)
        ), nearby AS (
          SELECT port_id,event_id,distance_meters,
                 {band_case} AS proximity_band
          FROM measured
        )
        INSERT INTO port_event_exposure (port_id,event_id,distance_meters,distance_km,proximity_band,calculated_at)
        SELECT port_id,event_id,distance_meters,distance_meters/1000.0,proximity_band,:calculated_at
        FROM nearby WHERE proximity_band IS NOT NULL
        ON CONFLICT (port_id,event_id) DO UPDATE SET
          distance_meters=EXCLUDED.distance_meters,
          distance_km=EXCLUDED.distance_km,
          proximity_band=EXCLUDED.proximity_band,
          calculated_at=EXCLUDED.calculated_at
        RETURNING port_id,event_id,distance_meters,proximity_band
    """), {"max_meters": max_m, "calculated_at": now}).mappings().all()
    # Remove relationships that no longer meet the configured search area after a recalculation.
    session.execute(text("DELETE FROM port_event_exposure e WHERE NOT EXISTS (SELECT 1 FROM silver_ports p JOIN silver_earthquakes q ON p.port_id=e.port_id AND q.event_id=e.event_id WHERE ST_DWithin(p.location,q.location,:max_meters))"), {"max_meters": max_m})
    session.flush()
    result = {"relationships": len(rows), "calculated_at": now.isoformat(), "thresholds_km": thresholds, "max_radius_km": thresholds[-1], "duration_seconds": round(perf_counter() - started, 3)}
    log.info("spatial association result=%s", result)
    return result
