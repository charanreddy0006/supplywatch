"""Database-backed quality rule catalog and evaluators."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from config.settings import Settings
from config.spatial import EXPOSURE_BOUNDARY_TOLERANCE_METERS
from database.models import BronzePort, BronzeEarthquake
from quality.validators import ValidationError, validate_port, validate_earthquake
from quality.quarantine import store_quarantine


@dataclass
class Evaluation:
    total: int
    issues: list[dict]
    excluded: int = 0
    diagnostics: dict | None = None


@dataclass
class QualityRule:
    rule_id: str
    name: str
    description: str
    dataset: str
    severity: str
    dimension: str
    expected: str
    evaluator: Callable[[Session], Evaluation]
    validation_layer: str = "silver_database"


def _scalar(session, query, params=None):
    return int(session.execute(text(query), params or {}).scalar_one())


def _sql_eval(total_sql, issue_sql, params=None, issue_fn=None, excluded=0, diagnostic=None):
    def evaluate(session):
        total = _scalar(session, total_sql, params)
        rows = session.execute(text(issue_sql), params or {}).mappings().all()
        issues = [issue_fn(row) if issue_fn else dict(row) for row in rows]
        return Evaluation(total, issues, excluded if isinstance(excluded, int) else excluded(session), diagnostic or {})
    return evaluate


def _query_issues(sql, params=None, expected_key="expected", error="Validation failed"):
    def build(row):
        value = dict(row)
        entity = value.pop("entity_identifier", None)
        payload_id = value.pop("bronze_id", None)
        row_ids = value.pop("bronze_ids", None)
        return {"entity_identifier": str(entity) if entity is not None else None,
                "observed_value": value, "error_description": error,
                "_bronze_id": payload_id, "_bronze_ids": row_ids,
                "_original_payload": value.pop("_original_payload", None)}
    return sql


def _rule(rule_id, name, description, dataset, severity, dimension, expected, total_sql, issue_sql, params=None, error=None, excluded=0, issue_fn=None):
    if issue_fn is None:
        def issue_fn(row):
            value=dict(row)
            entity=value.pop("entity_identifier", None)
            value.pop("expected", None)
            observed=value.pop("observed", value)
            return {"entity_identifier":str(entity) if entity is not None else None,
                    "observed_value":observed,"error_description":error or description}
    return QualityRule(rule_id, name, description, dataset, severity, dimension, expected,
        _sql_eval(total_sql, issue_sql, params, issue_fn, excluded),
        "historical_tracking" if dataset=="history" else "exposure_analytics" if dataset=="exposure" else "pipeline_observability" if dataset=="pipeline" else "source_validation" if ".bronze_" in rule_id else "silver_database")


def _unsupported_mag_eval(session):
    supported = Settings.from_env().usgs_supported_magnitude_types
    total = _scalar(session, "select count(*) from silver_earthquakes where magnitude_type is not null")
    if not supported:
        return Evaluation(0, [], excluded=total, diagnostics={"reason": "USGS_SUPPORTED_MAGNITUDE_TYPES is unset; values are preserved without a guessed allowlist"})
    rows = session.execute(text("select event_id::text entity_identifier, magnitude_type observed_value from silver_earthquakes where magnitude_type is not null and lower(magnitude_type) <> all(:supported)"), {"supported": list(supported)}).mappings().all()
    return Evaluation(total, [{"entity_identifier": r["entity_identifier"], "observed_value": {"magnitude_type": r["observed_value"]}, "error_description": "Magnitude type is outside the configured USGS type catalog"} for r in rows])


def _freshness_eval(source):
    def evaluate(session):
        from analytics.historical import freshness_report
        threshold = Settings.from_env().freshness_thresholds_hours or {}
        result = next((r for r in freshness_report(session, threshold) if r["source"] == source), None)
        if result is None or result["latest_status"] == "failed":
            return Evaluation(1, [{"entity_identifier": source, "observed_value": result or {"status": "no_runs"}, "error_description": "Latest source attempt failed or no run is available"}])
        if result["stale"] is None:
            return Evaluation(0, [], excluded=1, diagnostics={"reason": "Freshness threshold is not configured or successful run is unavailable", "report": result})
        issues = [] if not result["stale"] else [{"entity_identifier": source, "observed_value": result, "error_description": "Latest successful source ingestion exceeds its configured freshness threshold"}]
        return Evaluation(1, issues, diagnostics={"report": result})
    return evaluate


def _port_bronze_payload_issues(session):
    rows = session.execute(text("""
        select id bronze_id, source_record_id::text entity_identifier, ingestion_run_id,
               raw_payload
        from bronze_ports b
        where nullif(btrim(raw_payload->'properties'->>'index_no'),'') is null
           or nullif(btrim(raw_payload->'properties'->>'port_name'),'') is null
           or ((raw_payload->'geometry'->'coordinates' is null)
               and (nullif(raw_payload->'properties'->>'latitude','') is null or nullif(raw_payload->'properties'->>'longitude','') is null))
    """)).mappings().all()
    issues=[]
    for row in rows:
        payload=dict(row["raw_payload"])
        payload["_source"]="OCHA GIS hosted layer: NGA World Port Index (Pub 150)"
        errors=validate_port(payload)
        issues.append({"entity_identifier":f"{row['entity_identifier']}#bronze-{row['bronze_id']}",
            "observed_value":{"bronze_id":row["bronze_id"],"source_record_id":row["entity_identifier"],"errors":[e.code for e in errors]},
            "error_description":"Bronze source payload fails port normalization rules",
            "_bronze_id":row["bronze_id"],"_original_payload":row["raw_payload"],"_ingestion_run_id":row["ingestion_run_id"],"_validation_errors":errors})
    total=_scalar(session,"select count(*) from bronze_ports")
    return Evaluation(total,issues)


def _bronze_duplicate_eval(table, source_id_col, data):
    def evaluate(session):
        total=_scalar(session,f"select count(*) from {table}")
        sql=f"""select source_record_id::text entity_identifier, ingestion_run_id,
            array_agg(id order by id) bronze_ids, count(*) duplicate_count
            from {table} where source_record_id is not null
            group by source, ingestion_run_id, source_record_id having count(*) > 1"""
        rows=session.execute(text(sql)).mappings().all()
        issues=[]
        for row in rows:
            issue={"entity_identifier":row["entity_identifier"],"observed_value":{"ingestion_run_id":row["ingestion_run_id"],"duplicate_count":row["duplicate_count"]},"error_description":"Stable source ID appears multiple times in one Bronze source run","_bronze_ids":row["bronze_ids"],"_ingestion_run_id":row["ingestion_run_id"],"_failed_records":int(row["duplicate_count"])}
            issues.append(issue)
        return Evaluation(total,issues)
    return evaluate


def _earthquake_bronze_payload_eval(session):
    rows=session.execute(text("""
      select id bronze_id, source_record_id::text entity_identifier, ingestion_run_id, raw_payload
      from bronze_earthquakes b
      where nullif(btrim(raw_payload->>'id'),'') is null
         or jsonb_typeof(raw_payload->'geometry'->'coordinates') <> 'array'
         or case when jsonb_typeof(raw_payload->'geometry'->'coordinates')='array' then jsonb_array_length(raw_payload->'geometry'->'coordinates') else 0 end < 2
    """)).mappings().all()
    issues=[]
    for row in rows:
        payload=dict(row["raw_payload"]); payload["_source"]="USGS FDSN Event Web Service"
        errors=validate_earthquake(payload)
        issues.append({"entity_identifier":f"{row['entity_identifier']}#bronze-{row['bronze_id']}","observed_value":{"bronze_id":row["bronze_id"],"errors":[e.code for e in errors]},"error_description":"Bronze source payload fails earthquake normalization rules","_bronze_id":row["bronze_id"],"_original_payload":row["raw_payload"],"_ingestion_run_id":row["ingestion_run_id"],"_validation_errors":errors})
    total=_scalar(session,"select count(*) from bronze_earthquakes")
    return Evaluation(total,issues)


def _port_rules():
    rules=[
      _rule("ports.required_fields","Required port fields","Stable ID and name are required.","ports","HIGH","completeness","Port ID and name are non-empty.","select count(*) from silver_ports","select port_id::text entity_identifier, jsonb_build_object('port_name',port_name) observed from silver_ports where nullif(btrim(port_id),'') is null or nullif(btrim(port_name),'') is null",error="Required port identity or name is missing"),
      _rule("ports.coordinate_range","Port coordinate ranges","Coordinates use WGS84 latitude/longitude bounds.","ports","HIGH","validity","-90 <= latitude <= 90; -180 <= longitude <= 180.","select count(*) from silver_ports","select port_id::text entity_identifier, jsonb_build_object('latitude',latitude,'longitude',longitude) observed from silver_ports where latitude not between -90 and 90 or longitude not between -180 and 180 or latitude in ('Infinity'::float8,'-Infinity'::float8,'NaN'::float8) or longitude in ('Infinity'::float8,'-Infinity'::float8,'NaN'::float8)",error="Port coordinates are invalid"),
      _rule("ports.geometry_srid_validity","Port geography validity","Stored geography must be valid SRID 4326 point geometry.","ports","HIGH","validity","Geometry is valid and ST_SRID is 4326.","select count(*) from silver_ports","select port_id::text entity_identifier, jsonb_build_object('srid',ST_SRID(location::geometry),'valid',ST_IsValid(location::geometry)) observed from silver_ports where ST_SRID(location::geometry)<>4326 or not ST_IsValid(location::geometry) or GeometryType(location::geometry)<>'POINT'",error="Port geography is invalid or has wrong SRID"),
      _rule("ports.source_metadata","Port source metadata","Every Silver port names its source.","ports","MEDIUM","completeness","Source is non-empty.","select count(*) from silver_ports","select port_id::text entity_identifier, jsonb_build_object('source',source) observed from silver_ports where nullif(btrim(source),'') is null",error="Port source metadata is missing"),
      _rule("ports.hash_format","Port hash format","Current content hashes are deterministic SHA-256 hex.","ports","HIGH","consistency","Content hash is 64 lowercase hexadecimal characters.","select count(*) from silver_ports","select port_id::text entity_identifier, jsonb_build_object('content_hash',content_hash) observed from silver_ports where content_hash !~ '^[0-9a-f]{64}$' or content_hash is null",error="Port hash is missing or malformed"),
      _rule("ports.last_seen_run","Port last-seen lineage","Last-seen run must exist, match source, and be completed.","ports","HIGH","referential_integrity","last_seen_run_id joins a completed run for the same source.","select count(*) from silver_ports","select p.port_id::text entity_identifier, jsonb_build_object('last_seen_run_id',p.last_seen_run_id,'run_status',r.status) observed from silver_ports p left join ingestion_runs r on r.run_id=p.last_seen_run_id and r.source_name=p.source where p.last_seen_run_id is null or r.run_id is null or r.status<>'completed'",error="Port last-seen run reference is absent or inconsistent"),
      _rule("ports.bronze_traceability","Port Bronze traceability","Every Silver port has source evidence in Bronze.","ports","HIGH","referential_integrity","Matching source ID exists in Bronze.","select count(*) from silver_ports","select p.port_id::text entity_identifier, jsonb_build_object('bronze_matches',count(b.id)) observed from silver_ports p left join bronze_ports b on b.source=p.source and b.source_record_id=p.port_id group by p.port_id having count(b.id)=0",error="Port has no matching Bronze source record"),
    ]
    rules.append(QualityRule("ports.bronze_payload_validity","Bronze port payload validity","Original port payloads satisfy ID/name/coordinate normalization rules.","ports","HIGH","validity","Raw payload has source ID, name, and a coordinate pair.",lambda s:_port_bronze_payload_issues(s),"source_validation"))
    rules.append(QualityRule("ports.bronze_unique_source_id","Bronze port ID uniqueness","A source ID occurs once per ingestion run.","ports","HIGH","uniqueness","No source/run/ID group has more than one feature.",_bronze_duplicate_eval("bronze_ports","source_record_id","port"),"source_validation"))
    rules.append(_rule("ports.silver_unique_id","Silver port ID uniqueness","Silver contains at most one row per stable port ID.","ports","CRITICAL","uniqueness","Each port_id occurs once.","select count(*) from silver_ports","select port_id::text entity_identifier,jsonb_build_object('count',count(*)) observed from silver_ports group by port_id having count(*)>1",error="Duplicate Silver port identity"))
    return rules


def _earthquake_rules():
    return [
      _rule("earthquakes.required_fields","Required earthquake fields","Event ID and event time are required.","earthquakes","HIGH","completeness","Event ID is non-empty and event_time is present.","select count(*) from silver_earthquakes","select event_id::text entity_identifier, jsonb_build_object('event_time',event_time) observed from silver_earthquakes where nullif(btrim(event_id),'') is null or event_time is null",error="Required earthquake identity or event time is missing"),
      _rule("earthquakes.coordinate_range","Earthquake coordinate ranges","Coordinates use WGS84 latitude/longitude bounds.","earthquakes","HIGH","validity","-90 <= latitude <= 90; -180 <= longitude <= 180.","select count(*) from silver_earthquakes","select event_id::text entity_identifier, jsonb_build_object('latitude',latitude,'longitude',longitude) observed from silver_earthquakes where latitude not between -90 and 90 or longitude not between -180 and 180 or latitude in ('Infinity'::float8,'-Infinity'::float8,'NaN'::float8) or longitude in ('Infinity'::float8,'-Infinity'::float8,'NaN'::float8)",error="Earthquake coordinates are invalid"),
      _rule("earthquakes.geometry_srid_validity","Earthquake geography validity","Stored geography must be valid SRID 4326 point geometry.","earthquakes","HIGH","validity","Geometry is valid and ST_SRID is 4326.","select count(*) from silver_earthquakes","select event_id::text entity_identifier, jsonb_build_object('srid',ST_SRID(location::geometry),'valid',ST_IsValid(location::geometry)) observed from silver_earthquakes where ST_SRID(location::geometry)<>4326 or not ST_IsValid(location::geometry) or GeometryType(location::geometry)<>'POINT'",error="Earthquake geography is invalid or has wrong SRID"),
      _rule("earthquakes.magnitude_finite","Earthquake magnitude validity","Magnitude may be null; populated values must be finite.","earthquakes","MEDIUM","validity","Magnitude is null or a finite numeric value; negative values are allowed.","select count(*) from silver_earthquakes","select event_id::text entity_identifier, jsonb_build_object('magnitude',magnitude) observed from silver_earthquakes where magnitude in ('Infinity'::float8,'-Infinity'::float8,'NaN'::float8)",error="Earthquake magnitude is non-finite"),
      QualityRule("earthquakes.magnitude_type_supported","Configured earthquake magnitude types","Type vocabulary is checked only against a configured catalog.","earthquakes","LOW","validity","Magnitude type is null or in USGS_SUPPORTED_MAGNITUDE_TYPES.",_unsupported_mag_eval),
      _rule("earthquakes.depth_finite","Earthquake depth validity","Depth may be null or signed per source semantics; populated values must be finite.","earthquakes","MEDIUM","validity","Depth is null or finite.","select count(*) from silver_earthquakes","select event_id::text entity_identifier, jsonb_build_object('depth_km',depth_km) observed from silver_earthquakes where depth_km in ('Infinity'::float8,'-Infinity'::float8,'NaN'::float8)",error="Earthquake depth is non-finite"),
      _rule("earthquakes.source_metadata","Earthquake source metadata","Every Silver event names its source.","earthquakes","MEDIUM","completeness","Source is non-empty.","select count(*) from silver_earthquakes","select event_id::text entity_identifier, jsonb_build_object('source',source) observed from silver_earthquakes where nullif(btrim(source),'') is null",error="Earthquake source metadata is missing"),
      _rule("earthquakes.hash_format","Earthquake hash format","Current content hashes are deterministic SHA-256 hex.","earthquakes","HIGH","consistency","Content hash is 64 lowercase hexadecimal characters.","select count(*) from silver_earthquakes","select event_id::text entity_identifier, jsonb_build_object('content_hash',content_hash) observed from silver_earthquakes where content_hash !~ '^[0-9a-f]{64}$' or content_hash is null",error="Earthquake hash is missing or malformed"),
      _rule("earthquakes.last_seen_run","Earthquake last-seen lineage","Last-seen run must exist, match source, and be completed.","earthquakes","HIGH","referential_integrity","last_seen_run_id joins a completed run for the same source.","select count(*) from silver_earthquakes","select q.event_id::text entity_identifier, jsonb_build_object('last_seen_run_id',q.last_seen_run_id,'run_status',r.status) observed from silver_earthquakes q left join ingestion_runs r on r.run_id=q.last_seen_run_id and r.source_name=q.source where q.last_seen_run_id is null or r.run_id is null or r.status<>'completed'",error="Earthquake last-seen run reference is absent or inconsistent"),
      _rule("earthquakes.bronze_traceability","Earthquake Bronze traceability","Every Silver event has source evidence in Bronze.","earthquakes","HIGH","referential_integrity","Matching source ID exists in Bronze.","select count(*) from silver_earthquakes","select q.event_id::text entity_identifier, count(b.id) bronze_matches from silver_earthquakes q left join bronze_earthquakes b on b.source=q.source and b.source_record_id=q.event_id group by q.event_id having count(b.id)=0",error="Earthquake has no matching Bronze source record"),
      QualityRule("earthquakes.bronze_payload_validity","Bronze earthquake payload validity","Original event payloads satisfy required ID and coordinate checks.","earthquakes","HIGH","validity","Raw payload has event ID and coordinate pair.",_earthquake_bronze_payload_eval,"source_validation"),
      QualityRule("earthquakes.bronze_unique_source_id","Bronze earthquake ID uniqueness","A source event ID occurs once per ingestion run.","earthquakes","HIGH","uniqueness","No source/run/ID group has more than one feature.",_bronze_duplicate_eval("bronze_earthquakes","source_record_id","earthquake"),"source_validation"),
      _rule("earthquakes.silver_unique_id","Silver event ID uniqueness","Silver contains at most one row per stable event ID.","earthquakes","CRITICAL","uniqueness","Each event_id occurs once.","select count(*) from silver_earthquakes","select event_id::text entity_identifier,jsonb_build_object('count',count(*)) observed from silver_earthquakes group by event_id having count(*)>1",error="Duplicate Silver earthquake identity"),
    ]


def _integrity_rules():
    settings=Settings.from_env()
    bands=sorted(settings.exposure_thresholds_km)
    case="CASE " + " ".join(f"WHEN distance_meters <= {v*1000+EXPOSURE_BOUNDARY_TOLERANCE_METERS} THEN 'Within {v:g} km'" for v in bands) + " ELSE NULL END"
    return [
      _rule("exposure.foreign_keys","Exposure referential integrity","Exposure rows reference current Silver ports and earthquakes.","exposure","CRITICAL","referential_integrity","Both related Silver rows exist.","select count(*) from port_event_exposure","select e.id::text entity_identifier, jsonb_build_object('port_id',e.port_id,'event_id',e.event_id) observed from port_event_exposure e left join silver_ports p using(port_id) left join silver_earthquakes q using(event_id) where p.port_id is null or q.event_id is null",error="Exposure references missing Silver record"),
      _rule("exposure.distance_consistency","Exposure distance consistency","Stored distances match PostGIS geography calculations.","exposure","HIGH","consistency","Distance differs from ST_Distance by at most 1 mm and km conversion within 1e-6.","select count(*) from port_event_exposure","select e.id::text entity_identifier, jsonb_build_object('stored_meters',e.distance_meters,'measured_meters',ST_Distance(p.location,q.location),'stored_km',e.distance_km) observed from port_event_exposure e join silver_ports p using(port_id) join silver_earthquakes q using(event_id) where abs(e.distance_meters-ST_Distance(p.location,q.location))>0.001 or abs(e.distance_km-e.distance_meters/1000.0)>0.000001",error="Exposure distance is inconsistent with PostGIS or km conversion"),
      QualityRule("exposure.threshold_consistency","Exposure threshold consistency","Stored band agrees with configured exposure thresholds.","exposure","HIGH","consistency",f"Band follows configured thresholds {bands} km.",_sql_eval("select count(*) from port_event_exposure",f"select id::text entity_identifier, jsonb_build_object('distance_meters',distance_meters,'proximity_band',proximity_band,'expected_band',{case}) observed from port_event_exposure where proximity_band is distinct from {case}")),
      _rule("exposure.unique_pair","Exposure pair uniqueness","Only one current relationship exists per port/event pair.","exposure","HIGH","uniqueness","No (port_id,event_id) group occurs more than once.","select count(*) from port_event_exposure","select port_id||':'||event_id entity_identifier, jsonb_build_object('count',count(*)) observed from port_event_exposure group by port_id,event_id having count(*)>1",error="Duplicate port/event exposure relationship"),
      _rule("history.valid_intervals","History effective-date consistency","Versions have positive, contiguous, non-overlapping intervals.","history","HIGH","consistency","valid_to > valid_from and each prior valid_to equals the next valid_from.","select count(*) from record_history","select source_record_id||':'||record_type entity_identifier, jsonb_build_object('valid_from',valid_from,'valid_to',valid_to,'next_from',next_from) observed from (select h.*, lead(valid_from) over(partition by source_name,source_record_id,record_type order by valid_from,id) next_from from record_history h) v where (valid_to is not null and valid_to<=valid_from) or (next_from is not null and (valid_to is null or valid_to<>next_from))",error="History interval is invalid, overlapping, or contains a gap"),
      _rule("history.current_hash_match","Current history hash matches Silver","The open history version hash equals the Silver content hash.","history","CRITICAL","consistency","Silver hash equals its open history hash.","select (select count(*) from silver_ports)+(select count(*) from silver_earthquakes)","select p.port_id::text entity_identifier, jsonb_build_object('silver_hash',p.content_hash,'history_hash',h.content_hash) observed from silver_ports p left join record_history h on h.source_name=p.source and h.source_record_id=p.port_id and h.record_type='port' and h.valid_to is null where h.id is null or p.content_hash is distinct from h.content_hash union all select q.event_id::text, jsonb_build_object('silver_hash',q.content_hash,'history_hash',h.content_hash) from silver_earthquakes q left join record_history h on h.source_name=q.source and h.source_record_id=q.event_id and h.record_type='earthquake' and h.valid_to is null where h.id is null or q.content_hash is distinct from h.content_hash",error="Silver content hash has no matching current historical version"),
      _rule("runs.metric_consistency","Ingestion metric consistency","Run outcomes do not exceed received records.","pipeline","MEDIUM","consistency","Inserted+updated+unchanged+rejected <= received.","select count(*) from ingestion_runs","select run_id||':'||source_name entity_identifier, jsonb_build_object('received',records_received,'outcomes',records_inserted+records_updated+records_unchanged+records_rejected) observed from ingestion_runs where records_inserted+records_updated+records_unchanged+records_rejected>records_received",error="Ingestion metrics exceed received source records"),
      _rule("history.baseline_provenance","Historical baseline provenance","Baseline versions are explicitly marked as backfills.","history","MEDIUM","consistency","Each baseline run version carries baseline_backfill provenance.","select count(*) from record_history","select id::text entity_identifier, jsonb_build_object('provenance',observation_provenance,'run_type',r.metadata->>'run_type') observed from record_history h join ingestion_runs r on r.run_id=h.ingestion_run_id and r.source_name=h.ingestion_source_name where r.metadata->>'run_type'='historical_baseline_backfill' and h.observation_provenance<>'baseline_backfill'",error="Baseline history provenance is inconsistent"),
    ]


def rules_for(dataset="all"):
    rules=_port_rules()+_earthquake_rules()+_integrity_rules()
    rules.extend([
        QualityRule("timeliness.ports","Port source freshness","Configured freshness threshold is respected.","ports","MEDIUM","timeliness","Successful ingestion is within its configured age threshold.",_freshness_eval("OCHA GIS hosted layer: NGA World Port Index (Pub 150)"),"pipeline_observability"),
        QualityRule("timeliness.earthquakes","Earthquake source freshness","Configured freshness threshold is respected.","earthquakes","MEDIUM","timeliness","Successful ingestion is within its configured age threshold.",_freshness_eval("USGS FDSN Event Web Service"),"pipeline_observability"),
    ])
    if dataset == "all": return rules
    if dataset == "ports": return [r for r in rules if r.dataset in {"ports","exposure","history","pipeline"}]
    if dataset == "earthquakes": return [r for r in rules if r.dataset in {"earthquakes","exposure","history","pipeline"}]
    if dataset == "integrity": return [r for r in rules if r.dataset in {"exposure","history","pipeline"}]
    raise ValueError("dataset must be all, ports, earthquakes, or integrity")


def evaluate_rule(session, rule: QualityRule):
    return rule.evaluator(session)


def quarantine_rule_failure(session, rule: QualityRule, issue: dict):
    payload=issue.get("_original_payload")
    errors=issue.get("_validation_errors")
    run_id=issue.get("_ingestion_run_id")
    if payload is not None and errors:
        source="OCHA GIS hosted layer: NGA World Port Index (Pub 150)" if rule.dataset=="ports" else "USGS FDSN Event Web Service"
        source_id=payload.get("properties",{}).get("index_no") if rule.dataset=="ports" else payload.get("id")
        store_quarantine(session,source,str(source_id) if source_id is not None else None,"port" if rule.dataset=="ports" else "earthquake",run_id,source,payload,errors)
        return
    bronze_ids=issue.get("_bronze_ids") or ([issue.get("_bronze_id")] if issue.get("_bronze_id") else [])
    if not bronze_ids:
        return
    model=BronzePort if rule.dataset=="ports" else BronzeEarthquake
    validation_issue=ValidationError("duplicate_source_id","HIGH","Duplicate stable source ID within one source run","one raw feature per stable source ID",issue.get("entity_identifier"))
    for record in session.execute(select(model).where(model.id.in_(bronze_ids))).scalars():
        store_quarantine(session,record.source,record.source_record_id,"port" if rule.dataset=="ports" else "earthquake",
            record.ingestion_run_id,record.source,record.raw_payload,[validation_issue])
