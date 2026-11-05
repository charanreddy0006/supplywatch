"""Show actual pipeline run, freshness, quality, quarantine, and history health."""
import argparse, json
from sqlalchemy.orm import Session
from database.connection import make_engine
from quality.reporting import pipeline_health_report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json",action="store_true",help="Emit JSON output (default)")
    args=parser.parse_args(); engine=make_engine()
    try:
        with Session(engine) as session: report=pipeline_health_report(session)
        print(json.dumps(report,indent=2,default=str))
        if report["health_status"] in {"FAILED","STALE"}: raise SystemExit(1)
    except SystemExit: raise
    except Exception as exc:
        print(f"Pipeline health report failed: {type(exc).__name__}: {exc}")
        raise SystemExit(2)
    finally: engine.dispose()


if __name__=="__main__": main()
