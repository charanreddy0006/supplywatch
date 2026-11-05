# SupplyWatch Day 4 implementation and verification

## Delivered

Day 4 adds an additive Alembic migration (`0003_quality_observability`), explicit provenance for the historical baseline, persistent quality execution/results/issues, source-record quarantine, dataset scorecards, and pipeline health reporting. The loader validates normalized records before Silver writes; invalid records retain their original payload and lineage in quarantine. Revalidation does not automatically release records.

The baseline command is safe to replay. It hashes current Silver business fields using the Day 3 canonical hashing rules, creates one initial history version per existing row, preserves each row's original `first_ingested_at`, and records that the observed baseline time is when history tracking began. It does not claim the records existed before that time.

## Live database verification

The existing PostgreSQL 16.4 / PostGIS 3.4 Compose database was migrated from `0002_historical_processing` to `0003_quality_observability`. The migration was additive and existing data was retained.

The live baseline initialized:

| Dataset | Silver rows | Hashes set | Initial history versions | Missing first-ingested time |
|---|---:|---:|---:|---:|
| Ports | 3,687 | 3,687 | 3,687 | 0 |
| Earthquakes | 1,817 | 1,817 | 1,817 | 0 |

Exposure rows remained at 28,028. A second baseline execution populated zero hashes and created zero history versions, confirming idempotency. The resulting database has 5,504 history versions and complete current Silver hash coverage.

The live quality execution was `9c7fec00-3c25-427e-b5ee-2a62d1e8a84c`. It evaluated 33 rules: 31 passed and two failed. The failures are both HIGH severity port source-data findings: the two retained Bronze features have duplicate source ID `0` and missing port names. They remain in Bronze and are quarantined; they were not inserted into Silver. The quality report records 9 open entity-level issues associated with those findings. No Silver, exposure, or historical consistency checks failed.

Earthquake magnitude type catalog checks were excluded because `USGS_SUPPORTED_MAGNITUDE_TYPES` is not configured; the implementation does not invent a closed vocabulary. Both source freshness states are `UNKNOWN` because `FRESHNESS_THRESHOLDS_HOURS` is not configured. The latest successful runs were about 0.13 hours old at verification, but the system does not label a source fresh without an operator threshold. Consequently pipeline health reports `FAILED` due to open HIGH issues, with source freshness `UNKNOWN`.

## Tests and reproduction

The complete suite passed against the migrated `supplywatch_test` database: **39 passed, 0 failed, 0 skipped**, including PostgreSQL/PostGIS, Day 3 regression, Day 4 baseline/quality/quarantine integration, and unit tests.

```powershell
alembic upgrade head
python -m scripts.initialize_history_baseline
python -m scripts.initialize_history_baseline  # idempotent replay
python -m scripts.run_quality_checks --dataset all
python -m scripts.quality_report --execution-id <execution-id>
python -m scripts.quarantine_report
python -m scripts.pipeline_health

$testUrl = 'postgresql+psycopg://supplywatch:change-me-locally@localhost:5433/supplywatch_test'
$env:DATABASE_URL = $testUrl
$env:SUPPLYWATCH_TEST_DATABASE_URL = $testUrl
python -m pytest -v
```

Set explicit source thresholds before using freshness as an operational alert. See [data quality](DATA_QUALITY.md) and [pipeline observability](OBSERVABILITY.md) for rule meanings, scorecard denominators, threshold configuration, and status behavior.

## Verification status

Implementation, additive migration, live baseline, idempotent replay, real-record quality execution, quarantine persistence, PostGIS checks, and regression tests were verified. The live data does contain unresolved high severity Bronze quality findings, and freshness cannot be classified without configured thresholds. These conditions are reported as-is and are not presented as a clean live quality state.
