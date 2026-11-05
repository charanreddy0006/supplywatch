# SupplyWatch

SupplyWatch is a data foundation for monitoring potential environmental exposure around global ports. It consolidates authentic port locations and observed earthquake events so future milestones can assess geographic proximity and environmental conditions. An earthquake near a port does not mean the port is closed; forecasts do not establish shipping delays.

## Day 1 architecture

```mermaid
flowchart LR
  A[OCHA hosted NGA WPI layer] --> C[Port extractor]
  B[USGS FDSN query API] --> D[Earthquake extractor]
  C --> E[Normalized JSON]
  D --> E
  A --> F[Immutable raw JSON]
  B --> F
  E --> G[Run manifest]
  F --> G
```

## Sources

- Ports: OCHA GIS public ArcGIS REST layer based on NGA World Port Index Pub 150. It provides WPI index, name, country and geometry. Details and attribution caveats are in [DATA_SOURCES.md](docs/DATA_SOURCES.md).
- Earthquakes: USGS FDSN Event Web Service query endpoint, requesting GeoJSON for a configurable date range (seven days by default).
- Open-Meteo Marine API was investigated for later use; no forecast ingestion is implemented.

## Stack

Python 3.11+, Requests, JSON, SQLAlchemy, Alembic, PostgreSQL/PostGIS, Pytest and Docker Compose. dbt, Airflow and Streamlit remain later milestones.

## Install and configure

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Settings are read from process environment variables and the ignored local `.env` file through `python-dotenv`. Shell environment values take precedence. No API credentials are needed for the implemented public endpoints.

Configurable variables include `SUPPLYWATCH_ENV`, `LOG_LEVEL`, `USGS_BASE_URL`, `USGS_DAYS`, `HTTP_CONNECT_TIMEOUT`, `HTTP_READ_TIMEOUT`, `HTTP_MAX_RETRIES`, `RAW_DATA_DIR`, and `PORTS_URL`.

## Run

```powershell
python main.py
```

The pipeline independently retrieves ports and earthquakes, saves successful raw and normalized data, writes a UTC manifest, and returns a nonzero exit code if either source fails. A verified 2026-11-02 run completed with `success`: ports 3,689 retrieved / 3,687 normalized (2 invalid); earthquakes 1,817 retrieved / 1,817 normalized (0 invalid, 0 duplicates). The run ID and exact paths are recorded in `data/raw/manifests/2026/11/ingestion_a7920caf0c5341169774b30bcef34a06.json`. Unit tests use mocked data and do not access public services.

## Tests

```powershell
python -m pytest -q
```

Tests cover HTTP retry behavior, schema normalization/validation, duplicates, empty/malformed payloads, and storage uniqueness/manifests.

## Storage

Raw source payloads are kept under `data/raw/<source>/YYYY/MM/`; manifests under `data/raw/manifests/YYYY/MM/`; normalized Day 1 records under `data/processed/<source>/YYYY/MM/`. Filenames include UTC microseconds and a unique run ID. Existing files are opened exclusively and never overwritten.

## Project structure

```text
config/                  environment settings
ingestion/clients/       reusable HTTP client
ingestion/extractors/    port and earthquake source logic
ingestion/models/        normalized records
ingestion/storage/       raw, normalized and manifest JSON
tests/                   isolated mocked tests
docs/                    source and architecture notes
scripts/                 runnable entry point
data/                    generated local data (not committed)
```

## Status

Implemented on Day 1: public-source research, source-specific extractors, validation and duplicate accounting, immutable raw capture, normalized outputs, manifests, partial failure handling, logging and unit tests. Live outcomes must be verified from a pipeline run and manifest; no sample execution counts are fabricated here.

## Day 2 — Geospatial Intelligence and Database Engineering

Day 2 adds a PostGIS database with immutable-per-run Bronze source evidence, normalized Silver records, and a persisted earthquake-to-port exposure table. It associates only observed event/port coordinates and does not label proximity as disruption.

### Start and migrate

```powershell
Copy-Item .env.example .env
# If host port 5432 is occupied, set POSTGRES_PORT=5433 and change
# DATABASE_URL's localhost port to 5433 in .env.
docker compose up -d
docker compose ps
python -m pip install -r requirements.txt
alembic upgrade head
python -m scripts.check_database
```

`check_database` runs `SELECT PostGIS_Version()`. Connect with `docker compose exec db psql -U supplywatch -d supplywatch`, and verify the extension with `SELECT PostGIS_Version();`. Stop the database with `docker compose down`; the named volume retains data. `docker compose down -v` removes that volume and is destructive.

Set `DATABASE_URL`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT` and `EXPOSURE_THRESHOLDS_KM` in `.env` or the environment. Keep the URL credentials and Compose credentials aligned. `.env` is ignored by git. Compose defaults are for local development only; change the placeholder password before use outside a local machine.

### Bronze and Silver

Alembic creates `bronze_ports`, `bronze_earthquakes`, `silver_ports`, `silver_earthquakes`, and `port_event_exposure`. Bronze stores each source GeoJSON feature as JSONB together with source ID, run ID, payload hash, and ingestion time. A run-scoped hash prevents duplicate capture on reruns while allowing source changes to be preserved in later runs. Silver uses stable WPI `index_no` and USGS event IDs as primary keys, validates coordinate ranges, and builds SRID 4326 points. Spatial columns use PostGIS `geography(Point,4326)`: its meter-based geodesic distance supports global proximity calculations without treating degrees as planar distances. GiST indexes support spatial filters.

Load the latest successful manifest run with `python -m scripts.load_database`, or choose one with `python -m scripts.load_database --run-id a7920caf0c5341169774b30bcef34a06`. `--raw-dir` and `--processed-dir` select alternate input roots. Re-running a run is idempotent; new source runs append Bronze evidence and upsert Silver by stable identity. Missing source records are retained rather than deleted.

### Exposure and queries

Run `python -m scripts.calculate_exposure`. PostGIS filters candidates with `ST_DWithin(geography, geography, max_meters)` and computes exact meter distances with `ST_Distance`; point creation uses longitude before latitude. `EXPOSURE_THRESHOLDS_KM=50,100,250` controls nested closest-applicable bands. Each pair is stored once and refreshed on recalculation. These are proximity bands, not damage thresholds.

Useful queries:

```sql
SELECT port_id, event_id, distance_km, proximity_band
FROM port_event_exposure ORDER BY distance_meters LIMIT 20;

SELECT p.country, count(DISTINCT p.port_id)
FROM silver_ports p JOIN port_event_exposure e USING (port_id)
GROUP BY p.country ORDER BY 2 DESC;

SELECT PostGIS_Version();
```

`python -m scripts.database_report` returns counts and distance band distribution from the database. Python analytics in `analytics/queries.py` also provides nearest-event, per-port-event, country grouping and latest event queries.

### Validation results (2026-11-03)

The Compose container is healthy on host port 5433 (5432 was occupied by a separate native PostgreSQL service). Verified versions: PostgreSQL 16.4 and PostGIS 3.4. Alembic revision `0001_initial` is current. The migration creates all five application tables, the two Silver geography GiST indexes, foreign keys, uniqueness constraints, and coordinate checks. `SELECT ST_AsText(ST_SetSRID(ST_MakePoint(72.8777,19.0760),4326))` returned `POINT(72.8777 19.076)`; a geography distance query returned meters.

The actual successful Day 1 run `a7920caf0c5341169774b30bcef34a06` was loaded. Database counts: Bronze ports 3,689; Bronze earthquakes 1,817; Silver ports 3,687; Silver earthquakes 1,817; exposure relationships 28,028. Silver rejected no additional rows; Day 1 had already excluded 2 invalid ports from normalized output while Bronze retained their raw evidence. The second loader run inserted 0 Bronze/Silver rows, counted 5,506 repeated Bronze features, and reported all 5,504 Silver rows unchanged. Database counts remained constant.

Exclusive exposure bands contain 1,380 pairs within 50 km, 5,164 within 50–100 km, and 21,484 within 100–250 km. Cumulative ports with at least one nearby event: 230 within 50 km, 395 within 100 km, 762 within 250 km. Example closest pair: WPI port `20140`, USGS event `aka2026vgrxfn`, 671.038 m. Farthest saved pair within the maximum radius: port `18520`, event `uw714131781`, 249,998.816 m. These relationships indicate proximity only.

The complete suite passed: 23 passed, 0 failed, 0 skipped, including four PostgreSQL/PostGIS integration tests against a separate migrated `supplywatch_test` database. Tests cover known geography distance and coordinate order; inclusive 50/100/250 km boundaries and near-boundary points; outside-radius exclusion; invalid coordinates; foreign keys; analytics; and calculation reruns. Controlled test records were rolled back and did not enter source or production-like data.

To run integration tests locally, create and migrate a disposable test DB (adjust port/password to match `.env`):

```powershell
docker compose exec db createdb -U supplywatch supplywatch_test
$testUrl = 'postgresql+psycopg://supplywatch:change-me-locally@localhost:5433/supplywatch_test'
$env:DATABASE_URL = $testUrl
alembic upgrade head
$env:SUPPLYWATCH_TEST_DATABASE_URL = $testUrl
python -m pytest -v
```

Known limits: loading defaults to the most recent successful run; missing later feed records are not deleted; current exposure rows are refreshed in place rather than stored as a full time series. Bronze preserves run evidence for future history/versioning. Day 3 can add dated snapshots and vetted environmental sources without converting proximity into a disruption claim.

Planned: Later orchestration and dashboard work.

## Limitations and attribution

Port data is a hosted WPI-derived layer and its refresh schedule and layer-specific reuse terms are unclear. Attribute both NGA WPI and OCHA GIS and verify current terms before redistribution. USGS records can be revised, and optional properties can be null. Proximity is not proof of operational impact. Marine forecasts are not navigation advice. See [source notes](docs/DATA_SOURCES.md) and [architecture](docs/ARCHITECTURE.md).

## Day 3: historical and incremental processing

Alembic revision `0002_historical_processing` adds database-backed source runs and effective-dated record history. The existing loader computes stable SHA-256 fingerprints over explicit business fields, updates Silver only for changed records, and creates historical versions in the same transaction. Bronze remains run-scoped and append-only; missing source records are never deleted.

```powershell
alembic upgrade head
python -m scripts.load_database --help
python -m scripts.history_report runs
python -m scripts.history_report versions port 20140
python -m scripts.history_report as-of port 20140 2026-11-01T00:00:00Z
python -m scripts.history_report freshness
python -m scripts.history_report compare <run-id-1> <run-id-2>
```

Set `FRESHNESS_THRESHOLDS_HOURS` to comma-separated `source-name=hours` values to enable stale/fresh evaluation, for example `FRESHNESS_THRESHOLDS_HOURS="USGS FDSN Event Web Service=24"`. With no configured threshold the report returns `stale: null`. Source event times, source publication/update times, and ingestion times remain distinct.

Each source is tracked independently in `ingestion_runs`; replaying the same terminal DB run is rejected to preserve its audit metrics. Run `alembic upgrade head` before loading. PostgreSQL integration tests require a disposable migrated database selected via `SUPPLYWATCH_TEST_DATABASE_URL`; see [Day 3 implementation](docs/DAY_3_IMPLEMENTATION.md).

## Day 4: historical baseline, data quality, and pipeline health

Migration `0003_quality_observability` adds persistent quality executions, rule results, issues, quarantine records, and history provenance. Initialize the actual Silver baseline after migrating:

```powershell
alembic upgrade head
python -m scripts.initialize_history_baseline
python -m scripts.initialize_history_baseline  # idempotency check
python -m scripts.run_quality_checks --dataset all
python -m scripts.quality_report --execution-id <execution-id>
python -m scripts.quarantine_report
python -m scripts.pipeline_health
```

Invalid rows are preserved in Bronze/quarantine and are excluded from Silver. Quarantine revalidation gates reprocessing; it never automatically releases a record. Scorecards report completeness, validity, uniqueness, consistency, timeliness, and referential integrity separately using the unweighted pass rate per rule-record evaluation. See [DATA_QUALITY.md](docs/DATA_QUALITY.md), [OBSERVABILITY.md](docs/OBSERVABILITY.md), and [DAY_4_IMPLEMENTATION.md](docs/DAY_4_IMPLEMENTATION.md).

Configure freshness operational targets through `FRESHNESS_THRESHOLDS_HOURS` using exact source names. An example is `FRESHNESS_THRESHOLDS_HOURS="OCHA GIS hosted layer: NGA World Port Index (Pub 150)=168,USGS FDSN Event Web Service=24"`; these are operator-defined thresholds. Missing thresholds report `UNKNOWN`. Configure `USGS_SUPPORTED_MAGNITUDE_TYPES` only when an approved source catalog is available.
