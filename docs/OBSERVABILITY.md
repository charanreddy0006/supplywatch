# SupplyWatch pipeline observability

`analytics.historical.freshness_report` and `quality.reporting.pipeline_health_report` combine source-specific runs, prior successful completion, complete snapshot time, attempt status, thresholds, quality execution/issues, quarantine status, and hash/history coverage.

Per-source health states are:

- `FRESH`: the latest attempt succeeded and elapsed time is within an explicitly configured threshold.
- `STALE`: a successful run exists and exceeds its configured threshold.
- `UNKNOWN`: no run exists, the last successful time is unavailable, or no threshold is configured.
- `FAILED`: the latest attempt failed. The earlier latest-success time remains reported separately.

An unknown source is never marked fresh. Complete snapshot freshness is reported independently from run success. Source event time, publication/update time, ingestion start, and processing completion remain separate fields.

## Configuration

`FRESHNESS_THRESHOLDS_HOURS` is a comma-separated map keyed by the exact database source name. The `.env.example` and runtime defaults configure the following operational targets:

```dotenv
FRESHNESS_THRESHOLDS_HOURS="OCHA GIS hosted layer: NGA World Port Index (Pub 150)=168,USGS FDSN Event Web Service=24"
```

The 168-hour port target reflects that the hosted layer has no stated refresh cadence and is checked weekly; the 24-hour USGS target is a daily monitoring interval for a frequently updated event service. These values are operator targets, not guarantees about provider publication schedules, and can be overridden for a deployment. An empty setting uses these documented defaults. Set a positive threshold for each exact source name to override. Use `USGS_SUPPORTED_MAGNITUDE_TYPES` only when a source catalog has been approved for that deployment.

## CLI

```powershell
python -m scripts.history_report freshness
python -m scripts.pipeline_health
python -m scripts.pipeline_health --json
python -m scripts.history_report runs
python -m scripts.quality_report --execution-id <execution-id>
```

Pipeline health includes latest run status and counts, last successful/complete timestamps, calculated age and threshold, open quality issues by severity, quarantine counts, and current hash/history coverage. Exit code 1 signals stale/failed health; unknown is reported and does not claim freshness.

The database-backed dashboard runs with `streamlit run dashboard.py`. It presents source run outcomes and computes freshness from the same configured thresholds. A later failed attempt is visible as `FAILED`, while the successful completion timestamp remains available for diagnosis.
