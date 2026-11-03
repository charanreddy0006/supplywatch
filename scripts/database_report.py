import json
from sqlalchemy import text
from sqlalchemy.orm import Session
from database.connection import make_engine
from analytics.queries import band_distribution, counts, exposed_ports_by_country

if __name__ == "__main__":
    engine = make_engine()
    try:
        with Session(engine) as session:
            report = {"counts": counts(session), "bronze": dict(session.execute(text("SELECT (SELECT count(*) FROM bronze_ports) ports,(SELECT count(*) FROM bronze_earthquakes) earthquakes")).mappings().one()), "bands": [dict(x) for x in band_distribution(session)], "top_countries": [dict(x) for x in exposed_ports_by_country(session)[:20]]}
            print(json.dumps(report, default=str, indent=2))
    finally: engine.dispose()
