# Novara

Multi-source web novel ingestion and serving platform.

## What is this?

Novara is the backend for a web novel reading platform that ingests stories
from many source sites, reconciles conflicting metadata, handles multiple
translators and versions, cleans chapter content, and serves clean canonical
data to a reader frontend.

The core principle:

> **One work can have many versions. One version can have many sources.
> One version chapter can have many source chapters.**

## Key Features

- **Layered data model**: Work → Version → SourceTitle → MetadataClaim / CoverCandidate / SourceChapter → VersionChapter
- **One adapter per source**: modular, independently testable, easy to extend
- **Raw data preservation**: scraped content is never modified; all cleaning runs on copies
- **Metadata claims**: field-level attribution from each source, resolved by confidence scoring
- **Chapter cleaning pipeline**: HTML sanitisation → boilerplate removal → paragraph repair → heading dedup
- **Quality scoring**: 0.0–1.0 scores for content and metadata completeness
- **Cover resolution**: downloads, inspects, and scores cover candidates
- **Work matching**: fuzzy deduplication of titles across sources
- **FastAPI serving layer**: REST API for works, versions, chapters, admin, and ingestion
- **Celery background tasks**: async ingestion and resolution jobs
- **PostgreSQL + SQLAlchemy 2.0 (async)**
- **Docker Compose for local development**

## Project Layout

```
novara/
├── config.py              # Settings from environment
├── database.py            # Async SQLAlchemy engine + session
├── models/                # All SQLAlchemy models
├── ingestion/
│   ├── base_adapter.py    # Abstract adapter contract
│   ├── registry.py        # Auto-discovery and lookup
│   ├── http_client.py     # Rate-limited async HTTP
│   ├── runner.py          # Ingestion orchestrator
│   └── adapters/          # One file per source site
│       ├── royalroad.py
│       └── wuxiaworld.py
├── cleaning/
│   ├── pipeline.py        # End-to-end cleaning orchestrator
│   ├── quality_scorer.py  # Content and metadata scoring
│   └── cleaners/          # Individual cleaning steps
│       ├── html_cleaner.py
│       ├── boilerplate_cleaner.py
│       ├── paragraph_fixer.py
│       └── heading_dedup.py
├── matching/
│   ├── work_matcher.py    # Cross-source work deduplication
│   └── version_matcher.py # Translator/version matching
├── resolution/
│   ├── metadata_resolver.py  # Best-claim selection per field
│   ├── cover_resolver.py     # Best cover selection
│   └── chapter_resolver.py   # Best chapter promotion
├── api/
│   ├── main.py            # FastAPI app
│   ├── routers/           # Route handlers
│   └── schemas/           # Pydantic request/response models
└── tasks/
    ├── celery_app.py      # Celery configuration
    └── ingestion_tasks.py # Background task definitions
```

## Quick Start

```bash
# Clone and configure
git clone https://github.com/slothking1/novara007
cd novara007
cp .env.example .env

# Start database and Redis
docker compose up db redis -d

# Run migrations
docker compose run --rm migrate

# Start API (with hot reload)
uvicorn novara.api.main:app --reload

# Start worker (in another terminal)
celery -A novara.tasks.celery_app worker --loglevel=info
```

Or start everything together:

```bash
docker compose up
```

API docs: http://localhost:8000/docs

## Running Tests

```bash
pip install -e ".[dev]"
pytest
```

## Documentation

- [Architecture](docs/architecture.md) — system design and data flow
- [Data Model](docs/data_model.md) — table reference
- [Adding a Source](docs/adding_a_source.md) — adapter onboarding guide

## Tech Stack

- Python 3.12
- FastAPI + uvicorn
- SQLAlchemy 2.0 (async) + asyncpg
- Alembic migrations
- PostgreSQL 17
- Redis + Celery
- httpx + BeautifulSoup4 + lxml
- bleach, ftfy, rapidfuzz, python-slugify
- pytest + respx + pytest-asyncio
