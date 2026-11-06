"""Database-backed SupplyWatch interactive dashboard."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine, text

from config.settings import Settings

st.set_page_config(page_title="SupplyWatch | Risk Intelligence", page_icon="🌐", layout="wide")
st.title("SupplyWatch")
st.caption("Global port and environmental exposure intelligence · Proximity does not confirm operational disruption")


@st.cache_resource
def get_engine(database_url: str):
    return create_engine(database_url, pool_pre_ping=True)


@st.cache_data(ttl=60)
def query(sql: str, database_url: str, params: dict | None = None) -> pd.DataFrame:
    try:
        with get_engine(database_url).connect() as connection:
            return pd.read_sql(text(sql), connection, params=params or {})
    except Exception as exc:
        st.error(f"Dashboard data query failed: {type(exc).__name__}: {exc}")
        st.info("Confirm migrations are current and the database matches DATABASE_URL.")
        st.stop()


settings = Settings.from_env()
try:
    with get_engine(settings.database_url).connect() as connection:
        connection.execute(text("SELECT 1"))
except Exception as exc:
    st.error(f"Cannot connect to the configured PostgreSQL database: {type(exc).__name__}: {exc}")
    st.info("Start the database, apply migrations, and check DATABASE_URL in .env.")
    st.stop()

counts = query("SELECT (SELECT count(*) FROM silver_ports) ports, (SELECT count(*) FROM silver_earthquakes) earthquakes, (SELECT count(*) FROM port_event_exposure) relationships", settings.database_url).iloc[0]
port_completeness = query("SELECT count(*) AS total, count(*) FILTER (WHERE latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180) AS valid_coordinates, count(*) FILTER (WHERE nullif(btrim(port_name),'') IS NULL OR country IS NULL) AS incomplete FROM silver_ports", settings.database_url).iloc[0]
within = query("SELECT count(DISTINCT port_id) ports, count(*) relationships FROM port_event_exposure WHERE distance_meters <= :radius", settings.database_url, {"radius": max(settings.exposure_thresholds_km) * 1000}).iloc[0]
health = query("SELECT source_name, status, started_at, completed_at, records_received, records_inserted, records_updated, records_unchanged, records_rejected, error FROM ingestion_runs ORDER BY started_at DESC LIMIT 20", settings.database_url)
quality = query("SELECT status, count(*) AS issue_count FROM quality_issues GROUP BY status", settings.database_url)
quarantine = query("SELECT status, count(*) AS record_count FROM quarantined_records GROUP BY status", settings.database_url)
history = query("SELECT record_type, change_type, count(*) AS versions FROM record_history GROUP BY record_type, change_type", settings.database_url)
open_high = int(query("SELECT count(*) AS n FROM quality_issues WHERE status='OPEN' AND severity IN ('CRITICAL','HIGH')", settings.database_url).iloc[0].n)
latest_success = query("SELECT max(completed_at) AS completed_at FROM ingestion_runs WHERE status='completed'", settings.database_url).iloc[0].completed_at

tabs = st.tabs(["Overview", "Port explorer", "Exposure intelligence", "History", "Data quality", "Pipeline"])
with tabs[0]:
    a, b, c, d = st.columns(4)
    a.metric("Global ports", f"{int(counts.ports):,}")
    b.metric("Earthquake events", f"{int(counts.earthquakes):,}")
    c.metric("Exposure relationships", f"{int(counts.relationships):,}")
    d.metric(f"Ports within {max(settings.exposure_thresholds_km):g} km", f"{int(within.ports):,}")
    st.caption(f"Valid coordinate ports: {int(port_completeness.valid_coordinates):,} / {int(port_completeness.total):,} · Incomplete name/country: {int(port_completeness.incomplete):,}")
    st.metric("Open high severity quality issues", open_high, delta="Review required" if open_high else "None", delta_color="inverse" if open_high else "normal")
    st.write("Last successful source run:", latest_success if pd.notna(latest_success) else "No successful runs recorded")
    bands = query("SELECT proximity_band, count(*) relationships, count(DISTINCT port_id) ports FROM port_event_exposure GROUP BY proximity_band ORDER BY min(distance_meters)", settings.database_url)
    if not bands.empty:
        st.plotly_chart(px.bar(bands, x="proximity_band", y="relationships", color="proximity_band", title="Exclusive exposure bands"), use_container_width=True)

with tabs[1]:
    ports = query("SELECT port_id, port_name, country, latitude, longitude FROM silver_ports ORDER BY port_name", settings.database_url)
    if ports.empty:
        st.info("No port records are stored yet.")
    else:
        countries = sorted(ports.country.dropna().unique().tolist())
        selected_countries = st.multiselect("Country", countries)
        search = st.text_input("Search port")
        filtered = ports
        if selected_countries:
            filtered = filtered[filtered.country.isin(selected_countries)]
        if search:
            filtered = filtered[filtered.port_name.str.contains(search, case=False, na=False) | filtered.port_id.str.contains(search, case=False, na=False)]
        st.caption(f"Showing {len(filtered):,} of {len(ports):,} ports")
        st.plotly_chart(px.scatter_geo(filtered, lat="latitude", lon="longitude", hover_name="port_name", hover_data=["country", "port_id"], title="Global port locations"), use_container_width=True)
        st.dataframe(filtered, use_container_width=True, hide_index=True)

with tabs[2]:
    radius = st.select_slider("Exposure radius (km)", options=list(settings.exposure_thresholds_km), value=max(settings.exposure_thresholds_km))
    exposed = query("""SELECT p.port_id,p.port_name,p.country,p.latitude,p.longitude,q.event_id,q.magnitude,q.event_time,q.place,
        e.distance_km,e.proximity_band FROM port_event_exposure e JOIN silver_ports p USING(port_id)
        JOIN silver_earthquakes q USING(event_id) WHERE e.distance_meters <= :radius ORDER BY e.distance_meters""", settings.database_url, {"radius": radius * 1000})
    st.caption("Environmental proximity only. This analysis does not establish port damage, closure, or shipping delays.")
    st.metric(f"Nearby event relationships within {radius:g} km", f"{len(exposed):,}")
    if exposed.empty:
        st.info("No stored exposure relationships meet this radius.")
    else:
        st.plotly_chart(px.scatter_geo(exposed, lat="latitude", lon="longitude", color="magnitude", hover_name="port_name", hover_data=["event_id", "event_time", "place", "distance_km"], title="Ports with nearby earthquake events"), use_container_width=True)
        st.dataframe(exposed, use_container_width=True, hide_index=True)

with tabs[3]:
    st.subheader("Stored historical versions")
    st.dataframe(history, use_container_width=True, hide_index=True)
    asof = st.text_input("As-of timestamp (ISO 8601, UTC)", placeholder="2026-11-01T00:00:00Z")
    record_type = st.selectbox("Record type", ["port", "earthquake"])
    record_id = st.text_input("Port ID or earthquake event ID")
    if asof and record_id:
        try:
            versions = query("""SELECT source_record_id,record_type,record_data,valid_from,valid_to,change_type
                FROM record_history WHERE record_type=:kind AND source_record_id=:identity AND valid_from <= :stamp
                AND (valid_to IS NULL OR valid_to > :stamp) ORDER BY valid_from DESC LIMIT 1""", settings.database_url, {"kind": record_type, "identity": record_id, "stamp": asof})
            st.dataframe(versions, use_container_width=True, hide_index=True) if not versions.empty else st.info("No version was observed at that timestamp.")
        except Exception as exc:
            st.error(f"Historical query failed: {type(exc).__name__}: {exc}")

with tabs[4]:
    st.subheader("Persisted quality findings")
    st.dataframe(quality, use_container_width=True, hide_index=True)
    st.subheader("Quarantined source records")
    st.dataframe(quarantine, use_container_width=True, hide_index=True)
    executions = query("SELECT execution_id,dataset,status,started_at,completed_at FROM quality_executions ORDER BY started_at DESC LIMIT 50", settings.database_url)
    st.subheader("Quality execution history")
    st.dataframe(executions, use_container_width=True, hide_index=True)
    rule_results = query("""SELECT r.rule_id,r.dataset,r.severity,r.dimension,r.passed,r.records_evaluated,
        r.records_passed,r.records_failed,r.records_excluded,r.executed_at
        FROM quality_rule_results r JOIN quality_executions e USING(execution_id)
        WHERE e.started_at=(SELECT max(started_at) FROM quality_executions)
        ORDER BY r.dataset,r.dimension,r.rule_id""", settings.database_url)
    st.subheader("Latest quality rule results")
    st.dataframe(rule_results, use_container_width=True, hide_index=True)

with tabs[5]:
    st.subheader("Recent source runs")
    if health.empty:
        st.info("No ingestion runs are recorded yet.")
    else:
        st.dataframe(health, use_container_width=True, hide_index=True)
    st.subheader("Source freshness")
    freshness = query("""SELECT source_name, max(completed_at) FILTER (WHERE status='completed') latest_success,
        max(started_at) latest_attempt, (array_agg(status ORDER BY started_at DESC))[1] latest_status
        FROM ingestion_runs GROUP BY source_name ORDER BY source_name""", settings.database_url)
    if freshness.empty:
        st.info("Freshness is UNKNOWN until successful ingestion is recorded.")
    else:
        now = pd.Timestamp.now(tz="UTC")
        for row in freshness.itertuples(index=False):
            limit = settings.freshness_thresholds_hours.get(row.source_name)
            if row.latest_status == "failed": status = "FAILED"
            elif pd.isna(row.latest_success) or limit is None: status = "UNKNOWN"
            else: status = "FRESH" if (now - pd.Timestamp(row.latest_success)).total_seconds() <= limit * 3600 else "STALE"
            st.write(f"**{row.source_name}: {status}** · latest success: {row.latest_success if pd.notna(row.latest_success) else 'none'} · threshold: {limit if limit else 'unconfigured'} hours")
    st.caption("Run outcomes preserve the last successful timestamp independently from later failed attempts.")
