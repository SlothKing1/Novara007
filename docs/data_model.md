# Novara — Data Model Reference

## Entity Relationship Overview

```
Work (1) ──────────────── (n) Version
                                  │
                              (1) └── (n) SourceTitle
                                            │
                                      ┌────┼────────────────┐
                                      │    │                │
                                    (n) MetadataClaim  (n) CoverCandidate
                                          │
                                      (n) SourceChapter
                                            │
                                          (FK) VersionChapter ◄── (1) Version
```

---

## Table: `works`

The abstract, canonical story record. Source-agnostic.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK, auto-generated |
| `slug` | TEXT | Unique URL-safe identifier |
| `title` | TEXT | Resolved canonical title |
| `original_language` | TEXT | BCP-47 (e.g. "zh", "ko") |
| `status` | TEXT | ongoing / completed / hiatus / dropped |
| `synopsis` | TEXT | Resolved best synopsis |
| `selected_cover_id` | UUID | FK → `cover_candidates.id` (denormalised) |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

---

## Table: `versions`

A readable variant of a Work — language + translator combination.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `work_id` | UUID | FK → works |
| `slug` | TEXT | Unique within work |
| `label` | TEXT | Human label (e.g. "WuxiaWorld (EN)") |
| `translator_group` | TEXT | Group name |
| `language` | TEXT | BCP-47 |
| `version_type` | TEXT | official / fan / mtl / original / revised |
| `is_active` | BOOLEAN | Still being updated |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

---

## Table: `source_titles`

One source site's page for a title.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `version_id` | UUID | FK → versions |
| `source_site` | TEXT | Adapter SITE_KEY (e.g. "royalroad") |
| `source_id` | TEXT | Site-internal ID |
| `source_url` | TEXT | Full URL |
| `raw_metadata` | JSONB | Preserved raw scraped metadata blob |
| `quality_score` | FLOAT | 0.0–1.0 metadata completeness |
| `last_scraped_at` | TIMESTAMPTZ | |
| `is_metadata_authoritative` | BOOLEAN | Admin override flag |

---

## Table: `metadata_claims`

One field-level claim from one source.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `source_title_id` | UUID | FK → source_titles |
| `field_name` | TEXT | One of the recognised field names |
| `raw_value` | TEXT | Exact scraped string |
| `normalised_value` | TEXT | After light standardisation |
| `claim_hash` | TEXT | MD5 of raw_value for dedup |
| `confidence` | FLOAT | 0.0–1.0 |
| `is_resolved` | BOOLEAN | True if this claim won its field |

**Recognised `field_name` values:**

`title` · `original_title` · `synopsis` · `status` · `original_language` ·
`author` · `artist` · `genres` · `tags` · `total_chapters` · `release_year` ·
`release_frequency` · `translator_group` · `publisher` · `cover_url`

---

## Table: `cover_candidates`

One candidate cover image from one source.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `source_title_id` | UUID | FK → source_titles |
| `source_url` | TEXT | Original image URL |
| `local_path` | TEXT | Path after download |
| `width` | INT | Pixels |
| `height` | INT | Pixels |
| `file_size` | INT | Bytes |
| `image_format` | TEXT | jpeg / png / webp |
| `quality_score` | FLOAT | 0.0–1.0 composite score |
| `is_selected` | BOOLEAN | True if chosen for Work |

---

## Table: `version_chapters`

The resolved, reader-facing chapter.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `version_id` | UUID | FK → versions |
| `chapter_number` | FLOAT | Allows e.g. 12.5 for interlude |
| `title` | TEXT | Resolved display title |
| `content` | TEXT | Cleaned text (paragraphs joined with `\n\n`) |
| `word_count` | INT | |
| `promoted_from_id` | UUID | FK → source_chapters |

---

## Table: `source_chapters`

Raw scraped chapter from one source site.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `source_title_id` | UUID | FK → source_titles |
| `version_chapter_id` | UUID | FK → version_chapters (nullable) |
| `source_url` | TEXT | Chapter page URL |
| `source_chapter_id` | TEXT | Site-internal ID |
| `chapter_number` | FLOAT | As parsed from the source |
| `source_title_text` | TEXT | Title as seen on the page |
| `raw_content` | TEXT | Raw HTML — never modified |
| `cleaned_content` | TEXT | Output of cleaning pipeline |
| `paragraph_count` | INT | After cleaning |
| `word_count` | INT | After cleaning |
| `quality_score` | FLOAT | 0.0–1.0 |
| `cleaner_version` | TEXT | Pipeline version string |
| `last_scraped_at` | TIMESTAMPTZ | |
| `last_cleaned_at` | TIMESTAMPTZ | |

---

## Table: `ingestion_jobs`

Audit log for ingestion runs.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `source_site` | TEXT | SITE_KEY |
| `source_url` | TEXT | |
| `source_title_id` | UUID | FK (nullable) |
| `job_type` | TEXT | full / chapters / chapter / covers |
| `status` | TEXT | pending / running / completed / failed |
| `error_message` | TEXT | Short error |
| `error_detail` | TEXT | Full traceback |
| `chapters_found` | INT | |
| `chapters_new` | INT | |
| `chapters_updated` | INT | |
| `extra` | JSONB | Adapter-specific metadata |
| `started_at` | TIMESTAMPTZ | |
| `completed_at` | TIMESTAMPTZ | |

---

## Resolution Flow

```
SourceTitle scraped
      │
      ▼
MetadataClaims created (one per field)
      │
      ▼
MetadataResolver picks winner per field
      │
      ▼
Work.{title, synopsis, status, ...} updated
      │
      ▼
CoverResolver picks best CoverCandidate
      │
      ▼
Work.selected_cover_id updated
      │
      ▼
ChapterResolver cleans SourceChapters
      │
      ▼
VersionChapter.content promoted from best SourceChapter
```
