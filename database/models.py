from datetime import datetime
from sqlalchemy import BigInteger, CheckConstraint, DateTime, Float, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from geoalchemy2 import Geography


class Base(DeclarativeBase):
    pass


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
