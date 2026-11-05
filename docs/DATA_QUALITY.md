# SupplyWatch data quality

## Execution model

`quality/validators.py` contains reusable source/normalization validators. `quality/rules.py` defines stable rule IDs, descriptions, dimensions, severities, expected conditions and database evaluators. `quality.engine` persists each execution, per-rule results, and entity-level issues. Source Bronze errors found during a run are preserved in `quarantined_records` with their original JSONB payload.

Validation layers are reported as `source_validation`, `normalization_validation` (for loader quarantine outcomes), `silver_database`, `historical_tracking`, `exposure_analytics`, and `pipeline_observability`. Each rule execution records evaluated/passed/failed/excluded record counts, expected conditions, observed diagnostics, and issue entities. One execution never hides failed rules; the CLI exits nonzero when any rule fails.

## Severity

| Severity | Meaning |
|---|---|
| CRITICAL | Core identity or referential integrity is broken; stop dependent processing. |
| HIGH | Record content, coordinates, lineage, hashes, or exposure/history consistency is invalid. |
| MEDIUM | Required source metadata or operational consistency needs review. |
| LOW | Non-blocking source vocabulary or optional field concern. |
| INFO | Context or observation that does not fail a validity check. |

Severity does not change a rule's pass/fail result. The engine retains every rule failure and issue. `quality_issues` is unique per execution, rule, and entity. Repeated failures in a later execution create a new audit issue row, preserving run history.

## Rule groups

- Ports: stable identifier/name, WGS84 ranges and geography validity, source metadata, SHA-256 format, last-seen run linkage, Bronze traceability, Bronze source payload validity, and Silver/Bronze identity uniqueness.
- Earthquakes: stable event ID/time, coordinate and geography checks, finite magnitude/depth while allowing null magnitudes and signed source depths, source metadata, hash format, run linkage, Bronze traceability, identity uniqueness, and optional configured magnitude type catalog.
- Platform: exposure foreign keys, duplicate pairs, PostGIS distance and km consistency, configured proximity band consistency, history intervals and current hashes, baseline provenance, and ingestion metric bounds.
- Timeliness: source-specific run age against configured thresholds. Missing thresholds or unavailable successful runs are excluded and reported as unknown.

The magnitude type check does not assume a closed USGS catalog. Set `USGS_SUPPORTED_MAGNITUDE_TYPES` to enable it; otherwise type values are preserved and excluded from that rule's denominator.

## Scorecard formula

For each dataset and dimension, the reported percentage is:

`100 × records_passed / (records_passed + records_failed)`

Excluded records do not enter the denominator. Counts are rule-record evaluations: a record checked by two rules contributes two evaluations. Rules are not combined with arbitrary weights, and no overall single quality score is produced. The scorecard lists the rule IDs included in every dimension.

## Quarantine workflow

`QUARANTINED → UNDER_REVIEW → READY_FOR_REPROCESSING → RESOLVED`

The loader validates before Silver writes. Invalid rows are rejected from Silver and written to quarantine with source/run identity where available, original payload, SHA-256 payload digest, error codes, severity, and timestamp. Historical Bronze-only rows can retain their original Bronze run ID even when that older run was never registered in the Day 3 run ledger. Quarantined rows are never automatically inserted into Silver. Revalidation can only mark a row ready after successful checks; `RESOLVED` follows an explicit external reprocessing step.

## CLI

```powershell
python -m scripts.run_quality_checks --dataset all
python -m scripts.run_quality_checks --dataset ports --json
python -m scripts.quality_report --execution-id <execution-id>
python -m scripts.quality_report --compare <first-execution-id> <second-execution-id>
python -m scripts.quarantine_report
python -m scripts.quarantine_report --status QUARANTINED
python -m scripts.quarantine_report --revalidate <record-id>
python -m scripts.quarantine_report --resolve <record-id> --notes "Reprocessed after review"
```

The `READY_FOR_REPROCESSING` state is a gate, not an automatic release. Dataset-level duplicate identity issues cannot be cleared by validating an individual payload alone.
