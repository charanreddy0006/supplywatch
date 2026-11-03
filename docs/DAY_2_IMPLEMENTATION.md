# Day 2 implementation record

## Delivered

- PostgreSQL/PostGIS Compose service with persistent volume, configurable local credentials/port, health check, and restart policy.
- SQLAlchemy ORM tables for Bronze source evidence, Silver validated records, and unique port/event exposure pairs.
- Alembic initial migration enables PostGIS and creates metadata-defined tables and spatial indexes.
- Run-scoped Bronze loading stores source GeoJSON feature payloads as JSONB, with original identifiers when available and a canonical SHA-256 payload fingerprint for idempotency.
- Silver loading validates coordinates and upserts by WPI and USGS stable identifiers. It preserves first ingestion timestamps and classifies new, changed, and unchanged records.
- PostGIS exposure calculation uses geography and `ST_DWithin` followed by `ST_Distance`; default bands are nested at 50, 100 and 250 km.
- Database query helpers and runnable check, load, calculate, and report commands.

## Design notes

The source files stay immutable. Bronze uniqueness is scoped by source, run, and payload hash; identical features in a repeated load are skipped, while a new source version in a later run remains auditable. Silver is the current normalized view, with one row per stable identity. Exposure rows are current recalculated relationships; their `calculated_at` indicates the latest calculation. A future dated snapshot table can preserve every calculation. Geography is chosen over planar geometry because the records span the globe and distances need meter semantics. `ST_MakePoint` receives longitude, then latitude.

## Verification and actual counts

Day 1 successful manifest `a7920caf0c5341169774b30bcef34a06` reports 3,689 port source features, 3,687 normalized ports, and 1,817 earthquake source and normalized records. The normalized files and matching raw JSON were present in the workspace. The source project's 14 existing tests pass; Day 2 adds unit tests for model metadata, geography SRID/index configuration, and invalid coordinate/threshold rejection.

The Docker CLI and Compose are installed. The Docker engine named pipe was absent; starting `com.docker.service` returned an access error. A native PostgreSQL 18 Windows service exists, but the configured `supplywatch` credentials were rejected. Thus the live migration, `PostGIS_Version()`, database load, exposure calculation, example database relationships, and PostgreSQL integration tests could not be run here. `pytest` reports 19 passed and 3 PostgreSQL/PostGIS integration checks skipped. No database counts, PostGIS version, exposure totals, or sample live distances are reported as successful. Use `python -m scripts.database_report` after bringing up Docker and loading data to capture them.

Run verification locally:

```powershell
docker compose up -d
alembic upgrade head
python -m scripts.check_database
python -m scripts.load_database
python -m scripts.calculate_exposure
python -m scripts.database_report
python -m pytest -q
```

## Limits and next milestone

The loader uses the latest successful Day 1 manifest by default; `--run-id` selects a specific prior run. Silver holds current records while Bronze retains run-level input. Exposure rows are refreshed in place and are not a full time series. This milestone does not assess damage, closure, vessel delay, dependencies, or risk scores. Day 3 should add dated snapshots and vetted environmental sources, plus a reproducible comparison of changed exposure pairs.
