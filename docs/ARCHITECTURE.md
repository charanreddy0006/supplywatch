# Day 1 architecture

## Integrated local workflow

`python -m scripts.run_full_pipeline` runs the source extractors, stores raw and normalized files plus a manifest, loads Bronze and Silver with history, initializes any missing baseline history idempotently, recalculates PostGIS exposure, executes persisted quality checks, and returns analytics and health. Database mutations after extraction use one SQLAlchemy transaction; an error rolls them back. The command does not claim success if an ingestion source fails or health is stale/failed. `UNKNOWN` freshness remains explicit when no successful evidence exists. `main.py` remains the extraction-only entry point.

The Streamlit dashboard in `dashboard.py` reads the configured PostgreSQL database directly. It has Overview, Port Explorer, Exposure Intelligence, Historical Analytics, Data Quality, and Pipeline Monitoring sections; it does not display fixture metrics as production data.

`main.py` coordinates configuration, one reusable `requests.Session` HTTP client, source extractors and file storage. Each source is handled independently: the complete original response is written to `data/raw/<source>/YYYY/MM/`, then validated records are written under `data/processed/<source>/YYYY/MM/`. One UTC manifest per run captures source state, counts, date range, paths, duration and errors.

The HTTP client uses bounded retries for connection/timeouts, HTTP 429 and server errors, honors numeric or HTTP-date `Retry-After`, and immediately surfaces permanent HTTP failures. Extractors validate required IDs/names, coordinate ranges and timestamps, count invalid entries and remove duplicate IDs. A source failure does not discard the other source's results; the overall exit code is nonzero and the manifest says `partial_failure`.

Raw payloads are immutable, uniquely named JSON files and are never replaced. Normalized outputs are deliberately separate and lightweight for Day 1. The manifest contains no credentials. Event timestamps and ingestion timestamps use UTC.

## Day 2 data platform

```mermaid
flowchart LR
  A[Day 1 immutable raw GeoJSON] --> B[Bronze JSONB by run]
  C[Day 1 normalized JSON] --> D[Coordinate and field validation]
  D --> E[Silver ports and earthquakes]
  E --> F[PostGIS geography GiST indexes]
  F --> G[ST_DWithin candidate filter]
  G --> H[ST_Distance in meters]
  H --> I[port_event_exposure]
  I --> J[SQL analytics]
```

Bronze retains original feature payloads, source IDs where present, run IDs, hashes and ingestion timestamps. Silver keys ports by WPI `index_no` and events by USGS event ID. Geographic point columns use `geography(Point,4326)` for ellipsoidal distance in meters and GiST indexing. The exposure processor filters at the maximum configured radius (default 250 km), assigns one closest applicable band, and upserts each unique pair. A 1 mm numerical tolerance keeps constructed points at a configured boundary inclusive despite floating point behavior. Missing events in a later feed are not deleted. Exposure is geographic proximity evidence only.

Historical validation notes from the earlier Day 2 phase reported PostgreSQL 16.4/PostGIS 3.4 and 3,689 Bronze port features, 1,817 Bronze earthquakes, 3,687 Silver ports, 1,817 Silver events, and 28,028 exposure pairs. These are not presented as current counts; see the dated final validation report for the current verification attempt.

The implementation entry points and actual environment constraints are recorded in [DAY_2_IMPLEMENTATION.md](DAY_2_IMPLEMENTATION.md).

## Day 3 historical processing

```mermaid
flowchart LR
  A[Source extraction and manifest] --> B[Per-source database run]
  B --> C[Bronze evidence by source run]
  B --> D[Canonical SHA-256 business-field hash]
  D --> E[Silver current state and last-seen run]
  D --> F[Effective-dated record_history]
  F --> G[As-of, change, and lineage queries]
  B --> H[Freshness and run metrics]
```

Day 3 adds `ingestion_runs` and `record_history`, while extending Silver rows with nullable `content_hash` and `last_seen_run_id`. History is effective-dated and stores source identity, normalized snapshot, source run lineage, and the observed time. Existing rows receive their available baseline on their next actual observation; no synthetic pre-migration versions are inserted. The loader hashes explicitly tracked port and earthquake fields, excluding ingestion metadata and exposure relationships. It leaves absent rows untouched, and measures missing observations only for explicitly complete snapshots. See [DAY_3_IMPLEMENTATION.md](DAY_3_IMPLEMENTATION.md) for schema, completeness rules, CLI, tests, and verification state.

## Day 4 quality and observability

```mermaid
flowchart LR
  A[Bronze source payloads] --> B[Reusable validators]
  B -->|valid| C[Silver current state]
  B -->|invalid| D[quarantined_records]
  C --> E[PostGIS and history rules]
  D --> F[Quality execution and issues]
  E --> F
  F --> G[Quality scorecards]
  H[Ingestion runs and thresholds] --> I[Pipeline health]
  G --> I
  J[Existing Silver baseline] --> K[Baseline runs and version snapshots]
  K --> E
```

Day 4 adds `0003_quality_observability`, a repeatable baseline initializer, persistent quality executions/results/issues, payload-preserving quarantine, six transparent quality dimensions, and pipeline health states. Baseline versions are stamped `baseline_backfill`; preserved Silver `first_ingested_at` remains original row metadata and is not represented as the baseline observation timestamp. Invalid Bronze-only source features remain auditable and are not inserted into Silver. See [DATA_QUALITY.md](DATA_QUALITY.md), [OBSERVABILITY.md](OBSERVABILITY.md), and [DAY_4_IMPLEMENTATION.md](DAY_4_IMPLEMENTATION.md).
