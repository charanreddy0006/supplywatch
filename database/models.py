from datetime import datetime
from sqlalchemy import BigInteger, CheckConstraint, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from geoalchemy2 import Geography


class Base(DeclarativeBase):
    pass


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running','completed','failed')", name="ck_ingestion_runs_status"),
        CheckConstraint("snapshot_completeness IN ('complete','partial','failed','unknown')", name="ck_ingestion_runs_completeness"),
        Index("ix_ingestion_runs_source_started", "source_name", "started_at"),
        Index("ix_ingestion_runs_status_started", "status", "started_at"),
    )
    run_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(200), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    snapshot_completeness: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    records_received: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    records_inserted: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    records_updated: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    records_unchanged: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    records_rejected: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    records_missing: Mapped[int | None] = mapped_column(BigInteger)
    error_message: Mapped[str | None] = mapped_column(Text)
    run_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class RecordHistory(Base):
    __tablename__ = "record_history"
    __table_args__ = (
        CheckConstraint("change_type IN ('initial','updated')", name="ck_record_history_change_type"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_record_history_valid_range"),
        CheckConstraint("observation_provenance IN ('source_ingestion','baseline_backfill')", name="ck_record_history_provenance"),
        ForeignKeyConstraint(["ingestion_run_id", "ingestion_source_name"], ["ingestion_runs.run_id", "ingestion_runs.source_name"], name="fk_history_ingestion_run"),
        Index("ix_record_history_identity_time", "source_name", "source_record_id", "record_type", "valid_from"),
        Index("ix_record_history_run", "ingestion_run_id"),
        Index("uq_record_history_current", "source_name", "source_record_id", "record_type", unique=True, postgresql_where=text("valid_to IS NULL")),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(100), nullable=False)
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    record_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingestion_run_id: Mapped[str] = mapped_column(String(100), nullable=False)
    ingestion_source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)
    observation_provenance: Mapped[str] = mapped_column(String(30), nullable=False, default="source_ingestion")


class QualityExecution(Base):
    __tablename__ = "quality_executions"
    __table_args__ = (
        CheckConstraint("status IN ('running','completed','failed')", name="ck_quality_executions_status"),
        ForeignKeyConstraint(["ingestion_run_id", "ingestion_source_name"], ["ingestion_runs.run_id", "ingestion_runs.source_name"], name="fk_quality_execution_ingestion_run"),
        Index("ix_quality_executions_started", "started_at"),
        Index("ix_quality_executions_dataset", "dataset", "started_at"),
    )
    execution_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset: Mapped[str] = mapped_column(String(40), nullable=False)
    ingestion_run_id: Mapped[str | None] = mapped_column(String(100))
    ingestion_source_name: Mapped[str | None] = mapped_column(String(200))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    execution_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class QualityRuleResult(Base):
    __tablename__ = "quality_rule_results"
    __table_args__ = (
        ForeignKeyConstraint(["execution_id"], ["quality_executions.execution_id"], ondelete="CASCADE", name="fk_quality_result_execution"),
        UniqueConstraint("execution_id", "rule_id", name="uq_quality_result_execution_rule"),
        Index("ix_quality_rule_results_rule_time", "rule_id", "executed_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[str] = mapped_column(String(36), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dataset: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    dimension: Mapped[str] = mapped_column(String(40), nullable=False)
    passed: Mapped[bool] = mapped_column(nullable=False)
    records_evaluated: Mapped[int] = mapped_column(BigInteger, nullable=False)
    records_passed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    records_failed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    records_excluded: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    expected_condition: Mapped[str] = mapped_column(String(1000), nullable=False)
    observed_value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_description: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    diagnostics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class QualityIssue(Base):
    __tablename__ = "quality_issues"
    __table_args__ = (
        CheckConstraint("status IN ('OPEN','ACKNOWLEDGED','RESOLVED')", name="ck_quality_issues_status"),
        ForeignKeyConstraint(["execution_id"], ["quality_executions.execution_id"], ondelete="CASCADE", name="fk_quality_issue_execution"),
        UniqueConstraint("execution_id", "rule_id", "entity_identifier", name="uq_quality_issue_execution_entity"),
        Index("ix_quality_issues_status_severity", "status", "severity"),
        Index("ix_quality_issues_dataset_entity", "dataset", "entity_identifier"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[str] = mapped_column(String(36), nullable=False)
    rule_result_id: Mapped[int] = mapped_column(ForeignKey("quality_rule_results.id", ondelete="CASCADE"), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    dataset: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_identifier: Mapped[str | None] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    expected_condition: Mapped[str] = mapped_column(String(1000), nullable=False)
    observed_value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_description: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")


class QuarantinedRecord(Base):
    __tablename__ = "quarantined_records"
    __table_args__ = (
        CheckConstraint("status IN ('QUARANTINED','UNDER_REVIEW','READY_FOR_REPROCESSING','RESOLVED')", name="ck_quarantined_records_status"),
        CheckConstraint("severity IN ('CRITICAL','HIGH','MEDIUM','LOW','INFO')", name="ck_quarantined_records_severity"),
        Index("ix_quarantined_records_status", "status", "quarantined_at"),
        Index("ix_quarantined_records_identity", "source_name", "source_record_id"),
        Index("ix_quarantined_records_run", "ingestion_run_id", "ingestion_source_name"),
        UniqueConstraint("source_name", "ingestion_run_id", "ingestion_source_name", "identity_key", name="uq_quarantine_source_run_identity"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(100))
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    ingestion_run_id: Mapped[str | None] = mapped_column(String(100))
    ingestion_source_name: Mapped[str | None] = mapped_column(String(200))
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_key: Mapped[str] = mapped_column(String(200), nullable=False)
    original_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    error_codes: Mapped[list] = mapped_column(JSONB, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    quarantined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="QUARANTINED")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    reprocess_attempts: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class BronzePort(Base):
    __tablename__ = "bronze_ports"
    __table_args__ = (UniqueConstraint("source", "ingestion_run_id", "source_payload_hash", name="uq_bronze_port_source_record_run"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(100))
    source_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ingestion_run_id: Mapped[str] = mapped_column(String(100), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BronzeEarthquake(Base):
    __tablename__ = "bronze_earthquakes"
    __table_args__ = (UniqueConstraint("source", "ingestion_run_id", "source_payload_hash", name="uq_bronze_quake_source_record_run"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(100))
    source_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ingestion_run_id: Mapped[str] = mapped_column(String(100), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SilverPort(Base):
    __tablename__ = "silver_ports"
    __table_args__ = (CheckConstraint("latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180", name="ck_silver_ports_coordinates"),)
    port_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    port_name: Mapped[str] = mapped_column(String(300), nullable=False)
    country: Mapped[str | None] = mapped_column(String(100))
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    location = mapped_column(Geography(geometry_type="POINT", srid=4326, spatial_index=True), nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    last_seen_run_id: Mapped[str | None] = mapped_column(String(100))


class SilverEarthquake(Base):
    __tablename__ = "silver_earthquakes"
    __table_args__ = (CheckConstraint("latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180", name="ck_silver_quakes_coordinates"),)
    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    magnitude: Mapped[float | None] = mapped_column(Float)
    magnitude_type: Mapped[str | None] = mapped_column(String(30))
    place: Mapped[str | None] = mapped_column(String(500))
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    depth_km: Mapped[float | None] = mapped_column(Float)
    event_url: Mapped[str | None] = mapped_column(String(1000))
    event_type: Mapped[str | None] = mapped_column(String(100))
    location = mapped_column(Geography(geometry_type="POINT", srid=4326, spatial_index=True), nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    first_ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    last_seen_run_id: Mapped[str | None] = mapped_column(String(100))


class PortEventExposure(Base):
    __tablename__ = "port_event_exposure"
    __table_args__ = (UniqueConstraint("port_id", "event_id", name="uq_exposure_port_event"), Index("ix_exposure_port_distance", "port_id", "distance_meters"), Index("ix_exposure_band", "proximity_band"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    port_id: Mapped[str] = mapped_column(ForeignKey("silver_ports.port_id", ondelete="RESTRICT"), nullable=False)
    event_id: Mapped[str] = mapped_column(ForeignKey("silver_earthquakes.event_id", ondelete="RESTRICT"), nullable=False)
    distance_meters: Mapped[float] = mapped_column(Float, nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    proximity_band: Mapped[str] = mapped_column(String(30), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
