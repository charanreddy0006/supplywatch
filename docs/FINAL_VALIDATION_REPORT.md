# Final validation report

**Audit date:** 2026-11-06 (Asia/Kolkata)

## Scope and environment

The current repository was reviewed before edits. Python modules, migrations, Compose configuration, quality rules, CLI scripts, tests, and existing documentation were inspected. No data reset, volume deletion, migration, ingestion, or database write was performed during this audit because the configured database could not be reached.

Docker commands reported that the Docker engine named pipe was unavailable. A direct PostGIS check using the configured `localhost:5433` endpoint timed out. Therefore current database counts, migration revision, source quarantine payloads, and live dashboard queries could not be inspected. The earlier counts in prior implementation notes are historical claims and are not current verification.

## Code and test validation

- Baseline test run before edits: `30 passed, 9 skipped` in 4.82 seconds.
- Skipped tests are opt-in PostgreSQL/PostGIS tests requiring `SUPPLYWATCH_TEST_DATABASE_URL`.
- Database connection verification: failed with connection timeout at `localhost:5433`.
- Docker Compose status: unavailable because the Docker engine was not running/reachable.
- Live ingestion and full end-to-end pipeline: not run; source/database operational validation is pending.
- Dashboard UI and database retrieval: not run against a live database.

The nine skips mean there is no current PostGIS integration or database regression evidence. The passing tests do not establish live source extraction, SQL migration state, exposure calculations against current records, or end-to-end health.

## Data findings

The current record counts for Bronze ports, Bronze earthquakes, Silver ports, Silver earthquakes, history, exposure, quality issues, and quarantine are **unavailable** because database access failed. The current Alembic revision is also unavailable. The two malformed duplicate-ID features previously reported remain unaudited in this validation; their original payloads and exact validation failures require database access. No correction was invented or applied.

## Changes made in this phase

- Added configurable 168-hour WPI and 24-hour USGS freshness defaults, with positive-value validation and environment overrides.
- Added a local full-pipeline CLI chaining source extraction, loading, idempotent baseline completion, exposure, quality execution, and health output.
- Added a Streamlit dashboard backed by the configured database, covering overview, port exploration, exposure, history, quality/quarantine, and pipeline monitoring.
- Added dashboard dependencies and ignored Streamlit secrets/temp artifacts.
- Replaced stale README execution guidance and updated architecture/observability documents.

The new orchestration and dashboard still need a live database run. `requirements.txt` now includes Streamlit, Plotly, and pandas; the dashboard imports these at startup.

## Remaining validation steps

1. Start the existing database service/volume and verify its health without removing the volume.
2. Run `alembic current` and compare to `alembic heads`; apply `alembic upgrade head` only after inspecting current state and preserving the existing database.
3. Read the actual Bronze payloads and quarantine explanations for the two port records; confirm Silver excludes them.
4. Run the full quality and integrity checks, capture counts, and inspect issue transitions without suppressing legitimate findings.
5. Run `python -m scripts.run_full_pipeline` and check idempotency with a second run.
6. Set `SUPPLYWATCH_TEST_DATABASE_URL` only to a disposable PostgreSQL/PostGIS test database and run all integration tests.
7. Launch the Streamlit app and verify real query results and empty/error states.

No claims of full verification are made.
