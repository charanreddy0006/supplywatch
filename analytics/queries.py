from sqlalchemy import text
from sqlalchemy.orm import Session

def counts(session: Session):
    return dict(session.execute(text("SELECT (SELECT count(*) FROM silver_ports) ports,(SELECT count(*) FROM silver_earthquakes) earthquakes,(SELECT count(*) FROM port_event_exposure) relationships")).mappings().one())

def ports_within(session: Session, threshold_km: float):
    return session.execute(text("SELECT count(DISTINCT port_id) FROM port_event_exposure WHERE distance_meters <= :meters"), {"meters": threshold_km * 1000}).scalar_one()

def nearest_earthquake(session: Session, port_id: str):
    return session.execute(text("SELECT e.*,q.magnitude,q.event_time,q.place FROM port_event_exposure e JOIN silver_earthquakes q USING(event_id) WHERE e.port_id=:port_id ORDER BY e.distance_meters LIMIT 1"), {"port_id": port_id}).mappings().first()

def earthquakes_for_port(session: Session, port_id: str):
    return session.execute(text("SELECT q.*,e.distance_meters,e.distance_km,e.proximity_band,e.calculated_at FROM port_event_exposure e JOIN silver_earthquakes q USING(event_id) WHERE e.port_id=:port_id ORDER BY e.distance_meters"), {"port_id": port_id}).mappings().all()

def exposed_ports_by_country(session: Session):
    return session.execute(text("SELECT coalesce(p.country,'Unknown') country,count(DISTINCT p.port_id) exposed_ports FROM silver_ports p JOIN port_event_exposure e USING(port_id) GROUP BY p.country ORDER BY exposed_ports DESC,country")).mappings().all()

def latest_event_by_port(session: Session):
    return session.execute(text("SELECT DISTINCT ON (p.port_id) p.port_id,p.port_name,p.country,q.event_id,q.event_time,q.place,e.distance_km,e.proximity_band FROM silver_ports p JOIN port_event_exposure e USING(port_id) JOIN silver_earthquakes q USING(event_id) ORDER BY p.port_id,q.event_time DESC")).mappings().all()

def band_distribution(session: Session):
    return session.execute(text("SELECT proximity_band,count(*) relationships,count(DISTINCT port_id) ports FROM port_event_exposure GROUP BY proximity_band ORDER BY min(distance_meters)")).mappings().all()
