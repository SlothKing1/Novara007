# Novara — Architecture Overview

## What is Novara?

Novara is a multi-source web novel ingestion and serving platform.

Its purpose is not simply to scrape web novels. Its purpose is to build a
high-quality, normalised, deduplicated reading platform that can ingest the
same story from many different sites, handle conflicting metadata, multiple
translators, different cover images, and inconsistent chapter formatting — and
serve clean, canonical data to a reader-facing frontend.

---

## Core Principle

> **One work can have many versions. One version can have many sources.
> One version chapter can have many source chapters.**

This is the foundational idea. Everything in the system flows from it.

---

## Data Model Layers

```
Work
└── Version (translator group / language)
    └── SourceTitle (one site's record)
        ├── MetadataClaim (one field = one claim)
        ├── CoverCandidate (one image per source)
        └── SourceChapter (raw scraped chapter)
            └── VersionChapter (resolved, clean chapter)
```

### Work

The abstract, source-agnostic story. A Work exists independently of any
scraping source. Its canonical metadata fields (`title`, `synopsis`, `status`,
etc.) are populated by the **metadata resolver** from claims.

### Version

A readable variant of a Work — an official translation, a fan translation by
group X, a machine translation, the original language text. Multiple sites may
serve the same Version (mirrors), so SourceTitles can share a Version.

### SourceTitle

One source site's page for a story. Holds the raw scraped metadata blob and
links to MetadataClaims, CoverCandidates, and SourceChapters.

### MetadataClaim

A single field-level claim from a SourceTitle. Not automatically truth.
The resolver picks the winner per field based on confidence scores.

### CoverCandidate

One possible cover image. The cover resolver downloads, inspects, scores, and
selects the best candidate.

### VersionChapter

The resolved, reader-facing chapter. Its `content` is the cleaned text
promoted from the best-quality SourceChapter.

### SourceChapter

Raw scraped chapter data. Holds both `raw_content` (never modified) and
`cleaned_content` (output of the cleaning pipeline).

---

## Processing Stages

### 1. Ingestion

`IngestionRunner` orchestrates one scrape cycle for a SourceTitle:

1. Call the adapter's `scrape_title()` → emit MetadataClaims
2. Call `scrape_chapter_listing()` → create SourceChapter stubs
3. Call `scrape_chapter()` for each unseen chapter → save raw HTML

Adapters never write to the database directly. The runner handles all
persistence.

### 2. Matching

`WorkMatcher` links a newly ingested SourceTitle to a Work+Version:

- Exact slug match → reuse existing Work
- Fuzzy title match above threshold → reuse existing Work
- No match → create new Work + Version

`VersionMatcher` refines which Version within a Work a source belongs to,
based on language and translator group similarity.

### 3. Cleaning

`CleaningPipeline` processes raw chapter HTML through four stages:

1. **Unicode repair** — ftfy fixes encoding and mojibake
2. **HTML cleaner** — bleach + BeautifulSoup → list of plain-text paragraphs
3. **Boilerplate cleaner** — removes translator notes, nav text, ad content
4. **Paragraph fixer** — splits blob paragraphs, drops orphans
5. **Heading deduplicator** — removes leading title repetitions

### 4. Scoring

`QualityScorer` assigns a 0.0–1.0 score to:

- **SourceChapter** content (length, structure, cleanliness)
- **SourceTitle** metadata completeness

Scores are used by resolvers to pick winners.

### 5. Resolution

Three separate resolvers run independently and can be re-run without
re-scraping:

- **MetadataResolver** — picks the best MetadataClaim per field, writes to Work
- **CoverResolver** — downloads, scores, selects the best cover image
- **ChapterResolver** — cleans SourceChapters, promotes best to VersionChapter

---

## Source Adapters

Each source site has one adapter class in `novara/ingestion/adapters/`.
Adapters register themselves with `@register` and are auto-discovered at startup.

Adapters implement three methods:

- `scrape_title(url)` → `RawMetadata`
- `scrape_chapter_listing(url)` → `list[RawChapterListing]`
- `scrape_chapter(url)` → `RawChapterContent`

They do **not** parse, normalise, clean, or write to the database.
That is the runner's and pipeline's job.

See `docs/adding_a_source.md` for the onboarding guide.

---

## API

FastAPI app at `novara/api/main.py`.

| Route | Purpose |
|---|---|
| `GET /api/v1/works` | List all works |
| `GET /api/v1/works/{id_or_slug}` | Get work + versions |
| `POST /api/v1/works` | Create work manually |
| `GET /api/v1/versions/{id}/chapters` | List chapters |
| `GET /api/v1/versions/{id}/chapters/{num}` | Get clean chapter |
| `GET /api/v1/versions/{id}/chapters/{num}/sources` | Inspect all raw sources |
| `GET /api/v1/admin/sources/health` | Per-site health stats |
| `GET /api/v1/admin/works/{id}/claims` | Inspect all metadata claims |
| `POST /api/v1/admin/resolve` | Trigger resolution pass |
| `POST /api/v1/ingestion/jobs` | Queue ingestion job |
| `GET /api/v1/ingestion/jobs` | List jobs |
| `GET /api/v1/ingestion/adapters` | List registered adapters |

---

## Background Tasks

Celery + Redis.

| Task | Trigger |
|---|---|
| `run_ingestion_job` | API POST or beat schedule |
| `refresh_active_sources` | Hourly beat schedule |
| `resolve_work_task` | After ingestion completes |

---

## Local Development

```bash
cp .env.example .env
docker compose up db redis -d
docker compose run --rm migrate
uvicorn novara.api.main:app --reload
# In another terminal:
celery -A novara.tasks.celery_app worker --loglevel=info
```

Or run everything at once:

```bash
docker compose up
```

---

## Design Decisions

**Why preserve raw data?**
Cleaning pipelines can be improved. Resolvers can be retrained. We never want
to lose the original scraped text. `raw_content` on SourceChapter is written
once and never touched again.

**Why field-level claims instead of source-level metadata?**
Source quality is uneven per field, not globally. Source A might have the best
synopsis but a broken cover. Source B might have a better cover but a wrong
status. Claim-level resolution lets us pick the best field from the best source.

**Why conservative fuzzy matching?**
False merges (two different novels treated as one) are catastrophically harder
to recover from than false splits (one novel appearing as two Works). The
admin API supports manual merge corrections.

**Why Celery over asyncio task groups?**
Scraping is I/O-heavy and long-running. Celery gives retries, visibility,
scheduling, and worker isolation without blocking the API event loop.
