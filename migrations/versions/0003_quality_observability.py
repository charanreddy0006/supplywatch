"""Additive data quality, quarantine, and baseline provenance schema."""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_quality_observability"
down_revision = "0002_historical_processing"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    if context.is_offline_mode():
        return
    if "observation_provenance" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("record_history")}:
        op.add_column("record_history", sa.Column("observation_provenance", sa.String(30), nullable=False, server_default="source_ingestion"))
        op.alter_column("record_history", "observation_provenance", server_default=None)
    if "ck_record_history_provenance" not in {c["name"] for c in sa.inspect(op.get_bind()).get_check_constraints("record_history")}:
        op.create_check_constraint("ck_record_history_provenance", "record_history", "observation_provenance IN ('source_ingestion','baseline_backfill')")

    tables = _tables()
    if "quality_executions" not in tables:
        op.create_table(
            "quality_executions",
            sa.Column("execution_id", sa.String(36), primary_key=True),
            sa.Column("dataset", sa.String(40), nullable=False),
            sa.Column("ingestion_run_id", sa.String(100)),
            sa.Column("ingestion_source_name", sa.String(200)),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.ForeignKeyConstraint(["ingestion_run_id", "ingestion_source_name"], ["ingestion_runs.run_id", "ingestion_runs.source_name"], name="fk_quality_execution_ingestion_run"),
            sa.CheckConstraint("status IN ('running','completed','failed')", name="ck_quality_executions_status"),
        )
    if "quality_rule_results" not in tables:
        op.create_table(
            "quality_rule_results",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("execution_id", sa.String(36), nullable=False),
            sa.Column("rule_id", sa.String(100), nullable=False),
            sa.Column("rule_name", sa.String(200), nullable=False),
            sa.Column("dataset", sa.String(40), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False),
            sa.Column("dimension", sa.String(40), nullable=False),
            sa.Column("passed", sa.Boolean(), nullable=False),
            sa.Column("records_evaluated", sa.BigInteger(), nullable=False),
            sa.Column("records_passed", sa.BigInteger(), nullable=False),
            sa.Column("records_failed", sa.BigInteger(), nullable=False),
            sa.Column("records_excluded", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("expected_condition", sa.String(1000), nullable=False),
            sa.Column("observed_value", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("error_description", sa.Text()),
            sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("diagnostics", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.ForeignKeyConstraint(["execution_id"], ["quality_executions.execution_id"], ondelete="CASCADE", name="fk_quality_result_execution"),
            sa.UniqueConstraint("execution_id", "rule_id", name="uq_quality_result_execution_rule"),
        )
    if "quality_issues" not in tables:
        op.create_table(
            "quality_issues",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("execution_id", sa.String(36), nullable=False),
            sa.Column("rule_result_id", sa.BigInteger(), nullable=False),
            sa.Column("rule_id", sa.String(100), nullable=False),
            sa.Column("dataset", sa.String(40), nullable=False),
            sa.Column("entity_identifier", sa.String(200)),
            sa.Column("severity", sa.String(20), nullable=False),
            sa.Column("expected_condition", sa.String(1000), nullable=False),
            sa.Column("observed_value", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("error_description", sa.Text(), nullable=False),
            sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
            sa.ForeignKeyConstraint(["execution_id"], ["quality_executions.execution_id"], ondelete="CASCADE", name="fk_quality_issue_execution"),
            sa.ForeignKeyConstraint(["rule_result_id"], ["quality_rule_results.id"], ondelete="CASCADE", name="fk_quality_issue_result"),
            sa.UniqueConstraint("execution_id", "rule_id", "entity_identifier", name="uq_quality_issue_execution_entity"),
            sa.CheckConstraint("status IN ('OPEN','ACKNOWLEDGED','RESOLVED')", name="ck_quality_issues_status"),
        )
    if "quarantined_records" not in tables:
        op.create_table(
            "quarantined_records",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("source_name", sa.String(200), nullable=False),
            sa.Column("source_record_id", sa.String(100)),
            sa.Column("record_type", sa.String(30), nullable=False),
            sa.Column("ingestion_run_id", sa.String(100)),
            sa.Column("ingestion_source_name", sa.String(200)),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("identity_key", sa.String(200), nullable=False),
            sa.Column("original_payload", postgresql.JSONB(), nullable=False),
            sa.Column("error_codes", postgresql.JSONB(), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False),
            sa.Column("quarantined_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(timezone=True)),
            sa.Column("resolution_notes", sa.Text()),
            sa.Column("reprocess_attempts", sa.BigInteger(), nullable=False, server_default="0"),
            sa.CheckConstraint("status IN ('QUARANTINED','UNDER_REVIEW','READY_FOR_REPROCESSING','RESOLVED')", name="ck_quarantined_records_status"),
            sa.CheckConstraint("severity IN ('CRITICAL','HIGH','MEDIUM','LOW','INFO')", name="ck_quarantined_records_severity"),
            sa.UniqueConstraint("source_name", "ingestion_run_id", "ingestion_source_name", "identity_key", name="uq_quarantine_source_run_identity"),
        )

    for table, name, cols in (
        ("quality_executions", "ix_quality_executions_started", ["started_at"]),
        ("quality_executions", "ix_quality_executions_dataset", ["dataset", "started_at"]),
        ("quality_rule_results", "ix_quality_rule_results_rule_time", ["rule_id", "executed_at"]),
        ("quality_issues", "ix_quality_issues_status_severity", ["status", "severity"]),
        ("quality_issues", "ix_quality_issues_dataset_entity", ["dataset", "entity_identifier"]),
        ("quarantined_records", "ix_quarantined_records_status", ["status", "quarantined_at"]),
        ("quarantined_records", "ix_quarantined_records_identity", ["source_name", "source_record_id"]),
        ("quarantined_records", "ix_quarantined_records_run", ["ingestion_run_id", "ingestion_source_name"]),
    ):
        names = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}
        if name not in names:
            op.create_index(name, table, cols)


def downgrade():
    raise RuntimeError("Quality audit and quarantine history is retained; use a forward migration")
