# SupplyWatch interview demo guide

Use the configured database only if it is the intended demonstration environment. Do not run migrations or pipeline writes against a protected production database. For an isolated demo, use a dedicated local Compose database and its persistent volume.

## 1. Problem statement

Explain that the project combines global port locations and observed earthquake events to help inspect environmental exposure. Emphasize that geographic proximity is not evidence of port closure or supply-chain disruption.

## 2. Architecture walkthrough

Open the README architecture diagram. Trace source extraction, raw payload preservation, normalized records, Bronze/Silver tables, history, PostGIS exposure, quality/quarantine, and dashboard.

## 3. Data ingestion demonstration

Run `python main.py` to demonstrate independent source extraction and run manifests. Show the manifest's run ID, source statuses, timestamps, and retrieved/normalized/rejected counts. Avoid promising source availability in advance.

## 4. Bronze and Silver

Use `python -m scripts.database_report` for stored counts and explain that Bronze preserves source evidence while Silver contains valid normalized records. Show a quarantined source payload with `python -m scripts.quarantine_report` only when the actual local database has been checked.

## 5. PostGIS exposure query

Run `python -m scripts.calculate_exposure`, then show an actual nearest-event or exposure query. Explain that `ST_DWithin` narrows geography candidates and `ST_Distance` measures exact meters. Distinguish exclusive bands from cumulative radius statistics.

## 6. Historical tracking

Run `python -m scripts.history_report runs`, `python -m scripts.history_report versions port <id>`, and `python -m scripts.history_report as-of port <id> <ISO timestamp>` with a real stored ID. Explain that history starts at recorded observation/baseline time and cannot assert earlier changes.

## 7. Data quality and quarantine

Run `python -m scripts.run_quality_checks --dataset all` and `python -m scripts.quarantine_report`. Describe the actual findings and their status. Never remove a quality issue to make the demonstration look healthy, and do not present quarantined payloads as corrected without authoritative source evidence.

## 8. Dashboard walkthrough

Start `streamlit run dashboard.py`. Walk through Overview, Port Explorer, Exposure Intelligence, History, Data Quality, and Pipeline. The views query the configured database; displayed numbers should be read from that environment during the demo.

## 9. Engineering challenges and solutions

Discuss geodesic distance and coordinate order, idempotent loads, content hashes and historical versions, source-aware freshness, transaction boundaries, and preserving invalid evidence in quarantine. Close by describing the remaining limits: source cadence/coverage, no proof of operational disruption, and history only for observed records.
