"""Add database-backed runs and effective-dated source record history."""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_historical_processing"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    # 0001_initial is metadata-driven; on a fresh offline SQL generation it
    # already emits the current metadata schema, including these additions.
    if context.is_offline_mode():
        return
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "ingestion_runs" not in tables:
        op.create_table(
        "ingestion_runs",
        sa.Column("run_id", sa.String(100), primary_key=True),
        sa.Column("source_name", sa.String(200), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("snapshot_completeness", sa.String(20), nullable=False),
        sa.Column("records_received", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("records_inserted", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("records_updated", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("records_unchanged", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("records_rejected", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("records_missing", sa.BigInteger()),
        sa.Column("error_message", sa.Text()),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint("status IN ('running','completed','failed')", name="ck_ingestion_runs_status"),
        sa.CheckConstraint("snapshot_completeness IN ('complete','partial','failed','unknown')", name="ck_ingestion_runs_completeness"),
        )
    indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("ingestion_runs")}
    if "ix_ingestion_runs_source_started" not in indexes:
        op.create_index("ix_ingestion_runs_source_started", "ingestion_runs", ["source_name", "started_at"])
    if "ix_ingestion_runs_status_started" not in indexes:
        op.create_index("ix_ingestion_runs_status_started", "ingestion_runs", ["status", "started_at"])
    for table in ("silver_ports", "silver_earthquakes"):
        existing_cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
        for col, typ in (("content_hash", sa.String(64)), ("last_seen_run_id", sa.String(100))):
            if col not in existing_cols:
                op.add_column(table, sa.Column(col, typ))
    if "record_history" not in tables:
        op.create_table(
        "record_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_name", sa.String(200), nullable=False),
        sa.Column("source_record_id", sa.String(100), nullable=False),
        sa.Column("record_type", sa.String(30), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("record_data", postgresql.JSONB(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingestion_run_id", sa.String(100), nullable=False),
        sa.Column("ingestion_source_name", sa.String(200), nullable=False),
        sa.Column("change_type", sa.String(20), nullable=False),
        sa.ForeignKeyConstraint(["ingestion_run_id", "ingestion_source_name"], ["ingestion_runs.run_id", "ingestion_runs.source_name"], name="fk_history_ingestion_run"),
        sa.CheckConstraint("change_type IN ('initial','updated')", name="ck_record_history_change_type"),
        sa.CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_record_history_valid_range"),
        )
    foreign_keys = {fk.get("name") for fk in sa.inspect(op.get_bind()).get_foreign_keys("record_history")}
    if "fk_history_ingestion_run" not in foreign_keys:
        op.create_foreign_key("fk_history_ingestion_run", "record_history", "ingestion_runs", ["ingestion_run_id", "ingestion_source_name"], ["run_id", "source_name"])
    indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("record_history")}
    if "ix_record_history_identity_time" not in indexes:
        op.create_index("ix_record_history_identity_time", "record_history", ["source_name", "source_record_id", "record_type", "valid_from"])
    if "ix_record_history_run" not in indexes:
        op.create_index("ix_record_history_run", "record_history", ["ingestion_run_id", "ingestion_source_name"])
    if "uq_record_history_current" not in indexes:
        op.create_index("uq_record_history_current", "record_history", ["source_name", "source_record_id", "record_type"], unique=True, postgresql_where=sa.text("valid_to IS NULL"))


def downgrade():
    # This additive migration's data is operational history; downgrade is intentionally prohibited.
    raise RuntimeError("Historical processing data is retained; create a forward migration instead of downgrading")
