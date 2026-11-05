"""Initialize historical versions and hashes for existing Silver records."""
import argparse
import json
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from database.connection import make_engine
from database.models import RecordHistory, SilverPort, SilverEarthquake, PortEventExposure
from processing.baseline import initialize_baseline


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json",action="store_true",help="Emit machine-readable JSON (the default output is also JSON)")
    args=parser.parse_args()
    engine=make_engine()
    try:
        with Session(engine) as session, session.begin():
            before={"ports":session.scalar(select(func.count()).select_from(SilverPort)),
                    "earthquakes":session.scalar(select(func.count()).select_from(SilverEarthquake)),
                    "exposures":session.scalar(select(func.count()).select_from(PortEventExposure))}
            baseline=initialize_baseline(session)
            after={"ports":session.scalar(select(func.count()).select_from(SilverPort)),
                   "earthquakes":session.scalar(select(func.count()).select_from(SilverEarthquake)),
                   "exposures":session.scalar(select(func.count()).select_from(PortEventExposure)),
                   "ports_hashed":session.scalar(select(func.count()).select_from(SilverPort).where(SilverPort.content_hash.is_not(None))),
                   "earthquakes_hashed":session.scalar(select(func.count()).select_from(SilverEarthquake).where(SilverEarthquake.content_hash.is_not(None))),
                   "port_history_versions":session.scalar(select(func.count()).select_from(RecordHistory).where(RecordHistory.record_type=="port")),
                   "earthquake_history_versions":session.scalar(select(func.count()).select_from(RecordHistory).where(RecordHistory.record_type=="earthquake"))}
            report={"baseline":baseline,"before":before,"after":after,"exposure_relationships_preserved":before["exposures"]==after["exposures"],
                    "transaction":"committed"}
        print(json.dumps(report,indent=2,default=str))
    except Exception as exc:
        print(json.dumps({"error":f"{type(exc).__name__}: {exc}","transaction":"rolled_back"},indent=2))
        raise SystemExit(1)
    finally:
        engine.dispose()


if __name__=="__main__": main()
