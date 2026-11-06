"""Run ingestion through database analytics as one auditable local workflow."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from analytics.queries import counts, ports_within
from config.settings import Settings
from database.connection import make_engine
from main import run_pipeline as ingest_sources
from processing.baseline import initialize_baseline
from processing.loader import load_run
from processing.spatial_processor import calculate_exposures
from quality.engine import run_quality_checks
from quality.reporting import pipeline_health_report


def run_full_pipeline(settings: Settings | None = None) -> tuple[dict, int]:
    settings = settings or Settings.from_env()
    logger = logging.getLogger("supplywatch.full_pipeline")
    manifest, ingestion_code = ingest_sources(settings)
    run_id = manifest["run_id"]
    result: dict = {"run_id": run_id, "ingestion": manifest, "stages": {"ingestion": manifest["status"]}}
    if manifest["status"] == "failed":
        result["status"] = "FAILED"
        return result, 1

    engine = make_engine(settings.database_url)
    try:
        # The loader, baseline, exposure refresh and audit run share one commit.
        # Any failed required stage rolls back database mutations for this run.
        with Session(engine) as session, session.begin():
            load_result = load_run(session, settings.raw_data_dir, Path("data/processed"), run_id)
            result["load"] = load_result
            result["stages"]["bronze_silver_history"] = "success"
            baseline = initialize_baseline(session)
            result["baseline"] = baseline
            result["stages"]["baseline"] = "success"
            exposure = calculate_exposures(session, settings.exposure_thresholds_km)
            result["exposure"] = exposure
            result["stages"]["exposure"] = "success"
            quality = run_quality_checks(session, "all")
            result["quality"] = quality.to_dict()
            result["stages"]["quality"] = "success" if quality.status == "completed" else "failed"
            health = pipeline_health_report(session)
            result["health"] = health
            result["analytics"] = {
                "counts": counts(session),
                "ports_within_km": {str(radius): ports_within(session, radius) for radius in settings.exposure_thresholds_km},
            }
        result["status"] = "SUCCESS" if ingestion_code == 0 and result["health"]["health_status"] in {"FRESH", "UNKNOWN"} else "FAILED"
        return result, 0 if result["status"] == "SUCCESS" else 1
    except Exception:
        logger.exception("Full pipeline failed run_id=%s", run_id)
        result["status"] = "FAILED"
        result["stages"]["database_processing"] = "failed"
        raise
    finally:
        engine.dispose()


def main() -> None:
    settings = Settings.from_env()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        result, code = run_full_pipeline(settings)
        print(json.dumps(result, indent=2, default=str))
        raise SystemExit(code)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"SupplyWatch pipeline failed: {type(exc).__name__}: {exc}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
