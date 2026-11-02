# Day 1 architecture

`main.py` coordinates configuration, one reusable `requests.Session` HTTP client, source extractors and file storage. Each source is handled independently: the complete original response is written to `data/raw/<source>/YYYY/MM/`, then validated records are written under `data/processed/<source>/YYYY/MM/`. One UTC manifest per run captures source state, counts, date range, paths, duration and errors.

The HTTP client uses bounded retries for connection/timeouts, HTTP 429 and server errors, honors numeric or HTTP-date `Retry-After`, and immediately surfaces permanent HTTP failures. Extractors validate required IDs/names, coordinate ranges and timestamps, count invalid entries and remove duplicate IDs. A source failure does not discard the other source's results; the overall exit code is nonzero and the manifest says `partial_failure`.

Raw payloads are immutable, uniquely named JSON files and are never replaced. Normalized outputs are deliberately separate and lightweight for Day 1. The manifest contains no credentials. Event timestamps and ingestion timestamps use UTC.

For Day 2, the extractor output can be loaded into PostgreSQL Bronze tables alongside source payload references, then cleaned to Silver tables with deduplication and spatial association. Day 3 can build analytical tables and exposure indicators without labeling them as confirmed operations disruptions. Airflow on Day 4 can invoke the same pipeline functions as tasks; PostgreSQL/dbt transformations and dashboard reads remain later milestones.
