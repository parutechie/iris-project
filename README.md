## Project Structure

```
iris-sample/
├── main.py                          # CLI entry point
├── pyproject.toml                   # Dependencies (uv)
├── requirements.txt                 # Dependencies (pip)
├── docker-compose.yml               # PostgreSQL + PostGIS + pgAdmin
├── .env.example                     # Environment variable template
├── alembic/                         # Database migrations
│   └── versions/
├── app/
│   ├── ai/                          # AI prompts and keywords
│   ├── commands/                    # Command pattern wrappers
│   ├── config/                      # DataPaths, data sources
│   ├── database/
│   │   ├── base.py                  # SQLAlchemy DeclarativeBase
│   │   ├── session.py               # Engine + SessionLocal
│   │   ├── models/                  # ORM models
│   │   └── repositories/            # SQL query layer
│   ├── enrichers/                   # Power + BORIS enrichers
│   ├── extractors/                  # Entity extraction (MockExtractor)
│   ├── intelligence/                # News intelligence builder
│   ├── loaders/                     # Database loaders
│   ├── news/                        # RSS fetch, parse, extract, match
│   ├── parsers/                     # Signal ingest parser
│   ├── runners/                     # Pipeline orchestrators
│   ├── scrapers/                    # Signal ingest fetcher
│   └── services/                    # Business logic layer
├── ui/                              # Streamlit dashboard
├── tests/                           # Automated tests
│   ├── fixtures/                    # Sample data for tests
│   ├── test_signal_ingest_parser.py
│   └── test_signal_ingest_loader.py
└── scripts/                         # Standalone utilities and SQL queries
```

---

## Prerequisites

| Requirement    | Version | Notes                                |
| -------------- | ------- | ------------------------------------ |
| Python         | 3.12+   |                                      |
| Docker Desktop | latest  | For PostgreSQL + PostGIS             |
| uv             | latest  | Python package manager (recommended) |
| git            | any     |                                      |

**Install uv** (if you don't have it):

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

---

## Setup

Follow these steps in order the first time you set up the project.

### Step 1 — Clone the repository

```bash
git clone <repository-url>
cd iris-sample
```

### Step 2 — Create a virtual environment

```bash
uv venv
```

Activate it:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### Step 3 — Install dependencies

```bash
uv sync
```

Or with plain pip:

```bash
pip install -r requirements.txt
```

### Step 4 — Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and review the values. The defaults are pre-configured to match `docker-compose.yml`, so if you are using Docker you can leave them as-is:

```env
POSTGRES_DB=iris
POSTGRES_USER=iris_user
POSTGRES_PASSWORD=changeme
DATABASE_URL=postgresql://iris_user:changeme@localhost:5433/iris
OPENAI_API_KEY=sk-...        # optional — only needed for the AI Advisor
```

> **Security note:** Never commit `.env` to version control. It is listed in `.gitignore`.

### Step 5 — Start the database

```bash
docker-compose up -d
```

This starts two containers:

| Container     | What it is                  | Port                    |
| ------------- | --------------------------- | ----------------------- |
| `nrw-postgis` | PostgreSQL 17 + PostGIS 3.5 | `localhost:5433`        |
| `nrw-pgadmin` | pgAdmin 4 web UI            | `http://localhost:5050` |

Wait about 10 seconds for PostgreSQL to be healthy, then verify:

```bash
docker ps
```

You should see both containers with status `Up`.

> **Apple Silicon (M1/M2/M3) note:** The `docker-compose.yml` uses `imresamu/postgis:17-3.5` which provides native `linux/arm64` builds. The official `postgis/postgis` image does not support ARM64.

### Step 6 — Run database migrations

```bash
alembic upgrade head
```

This creates all schemas and tables:

| Schema         | Tables created                                                                                                              |
| -------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `iris_core`    | `facilities`, `news_articles`, `news_matches`, `energy_assets`, `land_values`, `power_infrastructure`, `osm_infrastructure` |
| `iris_staging` | `signal_ingest`                                                                                                             |

You should see output like:

```
INFO  [alembic.runtime.migration] Running upgrade ... -> c4f1a2d83e90, create iris_staging.signal_ingest
```

---

## Running the Pipeline

The platform has a single CLI entry point — `main.py`. Each pipeline component can be run individually or all together.

### Run a single command

```bash
python main.py <command>
```

Available commands:

| Command             | What it does                                                               |
| ------------------- | -------------------------------------------------------------------------- |
| `signal-ingest`     | Fetch Thomas Daily RSS → classify → load into `iris_staging.signal_ingest` |
| `news`              | Fetch DataCenter-Insider RSS → parse → extract entities                    |
| `entity-matcher`    | Match news entities against known facilities                               |
| `news-load`         | Load matched news into `iris_core.news_articles` + `news_matches`          |
| `news-intelligence` | Aggregate news signals onto facilities GeoJSON                             |
| `facilities`        | Scrape data center facilities                                              |
| `overpass`          | Fetch OSM infrastructure data                                              |
| `mastr`             | Fetch renewable energy data                                                |
| `site-score`        | Calculate site readiness scores                                            |
| `land-values`       | Load BORIS land value data                                                 |
| `all`               | Run the complete ETL pipeline end-to-end                                   |

### Example — run the signal ingest pipeline

```bash
python main.py signal-ingest
```

What happens:

```
[Step 1] Fetching Thomas Daily feed...
  → Attempts live RSS from https://www.thomas-daily.de/rss/feed/
  → If unreachable, falls back to tests/fixtures/thomas_daily_sample.json
  → Saves to: data/raw/signal_ingest/signal_raw.json

[Step 2] Parsing and classifying signals...
  → Parses publication dates to UTC datetimes
  → Classifies each article: brownfield_deal / logistics_purchase /
    commercial_transaction / unknown
  → Extracts city names from article text
  → Geocodes locations to EPSG:25832 via Nominatim (OpenStreetMap)
  → Saves to: data/processed/signal_ingest/signals.json

[Step 3] Loading into iris_staging.signal_ingest...
  → Upserts each record using source_url as the dedup key
  → First run: inserts all records
  → Subsequent runs: updates existing records, no duplicates created
  → Prints: Inserted / Updated / Skipped counts
```

### Run without geocoding (faster, no network needed)

```bash
python3 -c "
from app.runners.signal_ingest_runner import run
run(geocode_enabled=False)
"
```

Useful for offline demos or when you want to skip the ~1 second per article Nominatim delay.

### Run the full pipeline

```bash
python main.py all
```

This runs all four phases in sequence with an isolated run workspace:

```
[Phase 1] Data Acquisition      — facilities, markets, transformations
[Phase 2] Infrastructure        — OSM/Overpass, MaStR, BORIS
[Phase 3] Spatial Intelligence  — power enricher, site score
[Phase 4] Business Intelligence — news, entity matching, signal ingest, land values
```

### Re-running is safe

Every loader in the pipeline is **idempotent**. Re-running any command will update existing records rather than creating duplicates. This applies to `signal-ingest`, `news-load`, and all other loaders.

---

## Running the Dashboard

```bash
streamlit run ui/app.py
```

Open your browser at: **http://localhost:8501**

The dashboard requires a running database with data loaded. Run at least `python main.py signal-ingest` and `python main.py news-load` first to populate the business intelligence tables.

> The AI Advisor tab requires `OPENAI_API_KEY` to be set in `.env`.

---

## Running the Tests

The test suite requires no database and no network connection. All tests run against in-memory SQLite and the bundled fixture file.

```bash
python -m pytest tests/ -v
```

Expected output:

```
collected 46 items

tests/test_signal_ingest_loader.py::TestInsert::test_single_insert         PASSED
tests/test_signal_ingest_loader.py::TestInsert::test_record_persisted      PASSED
tests/test_signal_ingest_loader.py::TestInsert::test_multiple_inserts      PASSED
tests/test_signal_ingest_loader.py::TestIdempotency::test_rerun_...        PASSED
... (42 more)

46 passed in 0.3s
```

### What the tests cover

**`test_signal_ingest_loader.py` — 16 tests**

| Test class        | What is tested                                                                                   |
| ----------------- | ------------------------------------------------------------------------------------------------ |
| `TestInsert`      | Single insert, multiple inserts, records persisted correctly                                     |
| `TestIdempotency` | No duplicate on re-run, title update, signal type update, mixed insert+update batches, 3× re-run |
| `TestSkipping`    | Missing URL skipped, None URL skipped, mixed valid/invalid batch                                 |
| `TestGeometry`    | WKT stored correctly, NULL geometry stored correctly                                             |
| `TestParseErrors` | Error records inserted, error field cleared on recovery re-run                                   |

**`test_signal_ingest_parser.py` — 30 tests**

| Test class               | What is tested                                                                                                                                                                                     |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TestDateParsing`        | RFC 2822, ISO 8601, None, empty string, gibberish — all handled gracefully                                                                                                                         |
| `TestClassification`     | All four signal types, brownfield priority over logistics, case-insensitive matching                                                                                                               |
| `TestLocationExtraction` | City in title, city in summary, title preferred over summary, no match, partial match boundary                                                                                                     |
| `TestGeometryProjection` | Valid UTM 32N coordinates (Cologne), out-of-bounds rejection (New York), polar rejection                                                                                                           |
| `TestParseFixture`       | Full fixture run: record count, output file created, required fields present, signal types classified, locations extracted, dates parsed, error record handling, empty input, missing input raises |

---

## IRIS-SIG-42 — Signal Ingest

### Assignment summary

**Task ID:** IRIS-SIG-42  
**Integration Pattern:** D (Email / RSS Parser)  
**Target table:** `iris_staging.signal_ingest`  
**Objective:** Extract commercial transaction headlines, logistics purchases, and brownfield deals from a daily morning news feed and load them into PostgreSQL with idempotent operations.

---

### Data source

**Thomas Daily** (`https://www.thomas-daily.de`) is a German-language B2B news service publishing daily commercial real-estate transaction headlines, logistics property deals, and brownfield redevelopment news.

Public RSS feed:

```
https://www.thomas-daily.de/rss/feed/
```

No authentication required. Publishes new entries every morning in standard RSS 2.0.

**Source selection rationale:** The assignment brief states "source endpoint to be confirmed". Thomas Daily was selected because it is the primary German-language daily news service covering all three required signal types: commercial transactions, logistics purchases, and brownfield deals.

**Fixture fallback:** When the live feed is unreachable the fetcher automatically loads `tests/fixtures/thomas_daily_sample.json` (8 representative articles) so the pipeline runs and all tests pass without any network access. This behaviour is controlled by `FIXTURE_FALLBACK_ENABLED = True` in `app/scrapers/signal_ingest_fetcher.py`.

---

### Pipeline components

```
app/scrapers/signal_ingest_fetcher.py        Fetches RSS feed or loads fixture
app/parsers/signal_ingest_parser.py          Normalises, classifies, geocodes
app/loaders/signal_ingest_loader.py          Idempotent upsert to PostgreSQL
app/commands/load_signal_ingest_command.py   Command wrapper
app/runners/signal_ingest_runner.py          Orchestrates all three steps
app/database/models/signal_ingest.py         SQLAlchemy model
app/database/repositories/signal_ingest_repository.py
alembic/versions/c4f1a2d83e90_...py         Database migration
tests/test_signal_ingest_parser.py           30 parser tests
tests/test_signal_ingest_loader.py           16 loader / idempotency tests
tests/fixtures/thomas_daily_sample.json      8 representative fixture articles
scripts/validate_signal_ingest.sql           10 SQL validation queries
```

---

### Signal type classification

Each article is classified into one of four types by keyword matching against the German-language title and summary:

| Signal type              | Matched when text contains                                              |
| ------------------------ | ----------------------------------------------------------------------- |
| `brownfield_deal`        | brownfield, brachfläche, industriebrache, revitalisierung, konversion … |
| `logistics_purchase`     | logistikzentrum, spedition, fulfillment, umschlaghalle, supply chain …  |
| `commercial_transaction` | erworben, kauft, investiert, mio. euro, kaufpreis, übernimmt …          |
| `unknown`                | none of the above                                                       |

**Priority order:** brownfield → logistics → commercial → unknown.
A brownfield article that also mentions a logistics facility is always classified as `brownfield_deal`.

---

### Geographic context

City names are extracted from article text by word-boundary regex matching against a list of NRW and major German cities. Extracted names are geocoded to EPSG:25832 (UTM Zone 32N) using the Nominatim OpenStreetMap API.

| Situation                                | Result                                                                                             |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Single geocoding result                  | `location_resolved = true`, geometry stored                                                        |
| Multiple candidates                      | `location_resolved = true`, `location_ambiguous = true`, all candidates logged in `location_notes` |
| No result found                          | `location_resolved = false`, reason stored in `location_notes`                                     |
| Coordinates outside Germany bounding box | Geometry set to NULL, logged as warning                                                            |

Nominatim usage policy (1 request/second) is enforced with a 1.1-second delay between geocoding calls. No API key is required.

---

### Database table: `iris_staging.signal_ingest`

| Column               | Type                     | Description                                                                     |
| -------------------- | ------------------------ | ------------------------------------------------------------------------------- |
| `id`                 | `varchar(36)`            | UUID primary key                                                                |
| `source`             | `varchar(100)`           | Source name, e.g. `Thomas Daily`                                                |
| `source_url`         | `text`                   | Canonical article URL — **stable dedup key**                                    |
| `title`              | `text`                   | Article headline                                                                |
| `summary`            | `text`                   | Article excerpt                                                                 |
| `published_at`       | `timestamptz`            | Publication date (UTC)                                                          |
| `signal_type`        | `varchar(50)`            | `brownfield_deal` / `logistics_purchase` / `commercial_transaction` / `unknown` |
| `location_name`      | `varchar(255)`           | Raw city name extracted from text                                               |
| `location_resolved`  | `boolean`                | True when geometry was successfully geocoded                                    |
| `location_ambiguous` | `boolean`                | True when multiple geocoding candidates existed                                 |
| `location_notes`     | `text`                   | Geocoding notes, errors, or ambiguity details                                   |
| `latitude`           | `float`                  | WGS84 latitude                                                                  |
| `longitude`          | `float`                  | WGS84 longitude                                                                 |
| `geometry`           | `geometry(POINT, 25832)` | EPSG:25832 point geometry                                                       |
| `processed`          | `boolean`                | True after downstream processing                                                |
| `parse_error`        | `text`                   | Error message if parsing failed                                                 |
| `created_at`         | `timestamptz`            | Row creation time                                                               |
| `updated_at`         | `timestamptz`            | Row last update time                                                            |

---

### Idempotency guarantee

`source_url` is the stable deduplication key enforced by a `UNIQUE` constraint.

- **First run:** all records are inserted.
- **Subsequent runs:** existing records are updated in place — title, summary, signal type, location, and geometry are refreshed.
- **Duplicate records are never created**, regardless of how many times the pipeline runs.

This is verified by `TestIdempotency` in the test suite, including a test that runs the loader three times and asserts exactly one row exists.

---

### Field mapping

| RSS field          | Database column         | Transformation                           |
| ------------------ | ----------------------- | ---------------------------------------- |
| `<title>`          | `title`                 | Stripped whitespace                      |
| `<link>`           | `source_url`            | Stripped whitespace, dedup key           |
| `<description>`    | `summary`               | Stripped whitespace                      |
| `<pubDate>`        | `published_at`          | RFC 2822 → UTC datetime                  |
| Feed name          | `source`                | Hardcoded `"Thomas Daily"`               |
| Keyword match      | `signal_type`           | 4-way classification                     |
| First city in text | `location_name`         | Word-boundary regex                      |
| Nominatim lat/lon  | `latitude`, `longitude` | WGS84 floats                             |
| pyproj transform   | `geometry`              | `SRID=25832;POINT(easting northing)` WKT |

---

### SQL validation

After loading data, run the bundled validation queries:

```bash
psql $DATABASE_URL -f scripts/validate_signal_ingest.sql
```

The script runs 10 queries covering:

1. Signal type distribution
2. Deduplication check (should return 0 rows)
3. Missing required fields
4. Records with parse errors
5. Geocoding quality summary
6. Invalid geometry check (coordinates outside Germany)
7. Publication date coverage
8. Most recent 10 signals
9. Geographic coverage by city
10. All resolved geometries as WKT (for GIS visualisation)

---

### Known limitations

1. **Keyword classification** — not AI-driven. Accuracy can be improved by replacing `MockExtractor` with an `OpenAIExtractor` (the project already has the prompt and interface designed for this).

2. **One location per article** — the first matching city in title then summary is used. Articles mentioning multiple locations will only have one geometry.

3. **Nominatim rate limit** — 1 request per second. A feed with 50 articles takes ~1 minute for geocoding. A paid geocoding API (Google Maps, Here) would remove this constraint.

4. **Source URL as dedup key** — if the source changes its URL structure (e.g. adds tracking parameters), articles may be re-inserted. URL normalisation beyond whitespace stripping is not currently applied.

5. **RSS feed depth** — RSS feeds typically expose only the most recent 20–50 articles. Historical backfill requires a different approach (direct API or archived feed access).

---

## Project Status

| Area                                | Status         |
| ----------------------------------- | -------------- |
| ETL Pipelines                       | ✅ Complete    |
| GIS Dashboard                       | ✅ Complete    |
| Site Intelligence                   | ✅ Complete    |
| Site Score                          | ✅ Complete    |
| News Intelligence                   | ✅ Complete    |
| AI Advisor                          | ✅ Complete    |
| Signal Ingest (IRIS-SIG-42)         | ✅ Complete    |
| Context-aware AI / Intent Detection | 🔄 In Progress |
| LangGraph Integration               | 🔄 In Progress |
| Multi-Agent AI                      | 📋 Planned     |
| Predictive Site Recommendations     | 📋 Planned     |
| Voice Interface                     | 📋 Planned     |
