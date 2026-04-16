"""Frontend router — serves HTML pages and the JSON APIs expected by the frontend JS.

Page routes:
    GET /              → index.html
    GET /search        → search.html
    GET /browse        → search.html
    GET /novel/{slug}  → novel.html
    GET /novel/{slug}/chapter/{num} → chapter.html

JSON API routes (consumed by frontend JavaScript):
    GET /api/novels          → novel listing for homepage sections
    GET /api/search          → search with filters
    GET /api/stats           → site-wide counts
    GET /api/novels/{id}/similar → tag-based similar novels
    GET /api/novel/{slug}/chapters → chapter list for the drawer
    POST /api/library        → stub (localStorage-backed client side)
    POST /api/progress       → stub (localStorage-backed client side)
    POST /api/novels/{id}/reviews → stub (not yet implemented)
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from novara.database import get_session
from novara.models import Version, VersionChapter, Work

log = structlog.get_logger(__name__)

router = APIRouter(tags=["Frontend"])

# Templates instance — set by main.py after mounting
_templates: Jinja2Templates | None = None


def set_templates(t: Jinja2Templates) -> None:
    global _templates
    _templates = t


# ── SQL helpers ───────────────────────────────────────────────────────────────

# Correlated subqueries to enrich a work row without multiple JOIN fanouts
_WORK_COVER_SQ = """(
    SELECT COALESCE(cc.local_path, cc.source_url)
    FROM cover_candidates cc
    JOIN source_titles st ON st.id = cc.source_title_id
    JOIN versions v ON v.id = st.version_id
    WHERE v.work_id = w.id AND cc.is_selected = true
    LIMIT 1
)"""

_WORK_AUTHOR_SQ = """(
    SELECT mc.normalised_value
    FROM metadata_claims mc
    JOIN source_titles st ON st.id = mc.source_title_id
    JOIN versions v ON v.id = st.version_id
    WHERE v.work_id = w.id AND mc.field_name = 'author' AND mc.is_resolved = true
    LIMIT 1
)"""

_WORK_CHAPTER_COUNT_SQ = """(
    SELECT COUNT(vc.id)::int
    FROM version_chapters vc
    JOIN versions v ON v.id = vc.version_id
    WHERE v.work_id = w.id
)"""

_WORK_SELECT = f"""
    w.id,
    w.slug,
    w.title,
    w.status,
    w.original_language,
    LEFT(w.synopsis, 200) AS description,
    w.updated_at,
    w.created_at,
    {_WORK_COVER_SQ} AS cover_url,
    {_WORK_AUTHOR_SQ} AS author,
    {_WORK_CHAPTER_COUNT_SQ} AS total_chapters
"""

_ORDER_MAP = {
    "popular":  "COALESCE(total_chapters, 0) DESC, w.updated_at DESC NULLS LAST",
    "updated":  "w.updated_at DESC NULLS LAST, w.created_at DESC NULLS LAST",
    "new":      "w.created_at DESC NULLS LAST",
    "rating":   "w.updated_at DESC NULLS LAST",   # no ratings in v2 yet
    "chapters": "COALESCE(total_chapters, 0) DESC",
    "az":       "w.title ASC NULLS LAST",
}


def _row_to_dict(row: Any) -> dict:
    return {
        "id":               str(row.id),
        "slug":             row.slug or "",
        "title":            row.title or "",
        "author":           row.author or "Unknown",
        "cover_url":        row.cover_url,
        "status":           row.status or "ongoing",
        "total_chapters":   row.total_chapters or 0,
        "origin_language":  row.original_language or "",
        "avg_rating":       None,
        "description":      row.description or "",
    }


async def _fetch_works(
    session: AsyncSession,
    *,
    where: str = "1=1",
    params: dict,
    sort: str = "popular",
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    order = _ORDER_MAP.get(sort, _ORDER_MAP["popular"])
    sql = text(f"""
        SELECT {_WORK_SELECT}
        FROM works w
        WHERE {where}
        ORDER BY {order}
        LIMIT :limit OFFSET :offset
    """)
    count_sql = text(f"SELECT COUNT(*) FROM works w WHERE {where}")

    rows = (await session.execute(sql, {**params, "limit": limit, "offset": offset})).fetchall()
    total = (await session.execute(count_sql, params)).scalar_one() or 0
    return [_row_to_dict(r) for r in rows], total


# ── Page routes ───────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def homepage(request: Request) -> HTMLResponse:
    assert _templates is not None
    return _templates.TemplateResponse(request, "index.html", {})


@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, q: str = "") -> HTMLResponse:
    assert _templates is not None
    return _templates.TemplateResponse(request, "search.html", {"query": q})


@router.get("/browse", response_class=HTMLResponse)
async def browse_page(
    request: Request,
    sort: str = "popular",
    status: str = "",
) -> HTMLResponse:
    assert _templates is not None
    return _templates.TemplateResponse(
        request, "search.html", {"query": "", "sort": sort, "status": status}
    )


@router.get("/novel/{slug}", response_class=HTMLResponse)
async def novel_detail(
    request: Request,
    slug: str,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    assert _templates is not None

    # Fetch work
    work = await session.scalar(select(Work).where(Work.slug == slug))
    if not work:
        raise HTTPException(status_code=404, detail="Novel not found")

    # Cover
    cover_row = await session.execute(
        text(f"SELECT {_WORK_COVER_SQ} AS cover_url FROM works w WHERE w.id = :wid"),
        {"wid": work.id},
    )
    cover_url = cover_row.scalar_one_or_none()

    # Author
    author_row = await session.execute(
        text(f"SELECT {_WORK_AUTHOR_SQ} AS author FROM works w WHERE w.id = :wid"),
        {"wid": work.id},
    )
    author = author_row.scalar_one_or_none() or "Unknown"

    # Chapter count + listing (up to 2000)
    chapter_rows = await session.execute(
        text("""
            SELECT vc.chapter_number AS chapter_num, vc.title, vc.created_at
            FROM version_chapters vc
            JOIN versions v ON v.id = vc.version_id
            WHERE v.work_id = :wid
            ORDER BY vc.chapter_number ASC
            LIMIT 2000
        """),
        {"wid": work.id},
    )
    chapters = [dict(r._mapping) for r in chapter_rows.fetchall()]

    # Tags from metadata claims
    tag_rows = await session.execute(
        text("""
            SELECT DISTINCT mc.normalised_value AS raw
            FROM metadata_claims mc
            JOIN source_titles st ON st.id = mc.source_title_id
            JOIN versions v ON v.id = st.version_id
            WHERE v.work_id = :wid
              AND mc.field_name IN ('tags', 'genres')
              AND mc.is_resolved = true
            LIMIT 1
        """),
        {"wid": work.id},
    )
    tags: list[dict] = []
    for row in tag_rows.fetchall():
        raw = row.raw or ""
        # normalised_value may be comma-separated or JSON-ish
        for part in re.split(r"[,;\|]+", raw):
            part = part.strip().strip('"[]').lower()
            if part and len(part) < 40:
                tags.append({"name": part})

    novel = {
        "id":               str(work.id),
        "slug":             work.slug,
        "title":            work.title or "",
        "author":           author,
        "cover_url":        cover_url,
        "status":           work.status or "ongoing",
        "total_chapters":   len(chapters),
        "origin_language":  work.original_language or "",
        "avg_rating":       None,
        "description":      work.synopsis or "",
    }

    return _templates.TemplateResponse(request, "novel.html", {
        "novel":        novel,
        "tags":         tags,
        "chapters":     chapters,
        "reviews":      [],
        "review_count": 0,
    })


@router.get("/novel/{slug}/chapter/{chapter_num}", response_class=HTMLResponse)
async def read_chapter(
    request: Request,
    slug: str,
    chapter_num: int,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    assert _templates is not None

    work = await session.scalar(select(Work).where(Work.slug == slug))
    if not work:
        raise HTTPException(status_code=404, detail="Novel not found")

    # Fetch the chapter (nearest match)
    ch_row = await session.execute(
        text("""
            SELECT vc.*
            FROM version_chapters vc
            JOIN versions v ON v.id = vc.version_id
            WHERE v.work_id = :wid
            ORDER BY ABS(vc.chapter_number - :num) ASC
            LIMIT 1
        """),
        {"wid": work.id, "num": float(chapter_num)},
    )
    ch = ch_row.fetchone()
    if not ch:
        raise HTTPException(status_code=404, detail="Chapter not found")

    ch_dict = dict(ch._mapping)
    ch_dict["chapter_num"] = ch.chapter_number
    ch_dict["body"] = ch.content or ""
    ch_dict["paragraphs"] = _split_paragraphs(ch.content or "")

    # Prev / next
    prev_row = await session.execute(
        text("""
            SELECT vc.chapter_number AS chapter_num, vc.title
            FROM version_chapters vc
            JOIN versions v ON v.id = vc.version_id
            WHERE v.work_id = :wid AND vc.chapter_number < :num
            ORDER BY vc.chapter_number DESC
            LIMIT 1
        """),
        {"wid": work.id, "num": ch.chapter_number},
    )
    next_row = await session.execute(
        text("""
            SELECT vc.chapter_number AS chapter_num, vc.title
            FROM version_chapters vc
            JOIN versions v ON v.id = vc.version_id
            WHERE v.work_id = :wid AND vc.chapter_number > :num
            ORDER BY vc.chapter_number ASC
            LIMIT 1
        """),
        {"wid": work.id, "num": ch.chapter_number},
    )
    prev_ch = prev_row.fetchone()
    next_ch = next_row.fetchone()

    # Total chapter count
    total = await session.scalar(
        text("""
            SELECT COUNT(vc.id)::int
            FROM version_chapters vc JOIN versions v ON v.id = vc.version_id
            WHERE v.work_id = :wid
        """),
        {"wid": work.id},
    ) or 0

    # Cover
    cover_row = await session.execute(
        text(f"SELECT {_WORK_COVER_SQ} AS cover_url FROM works w WHERE w.id = :wid"),
        {"wid": work.id},
    )
    cover_url = cover_row.scalar_one_or_none()

    novel = {
        "id":              str(work.id),
        "slug":            work.slug,
        "title":           work.title or "",
        "cover_url":       cover_url,
        "total_chapters":  total,
        "description":     work.synopsis or "",
    }

    return _templates.TemplateResponse(request, "chapter.html", {
        "novel":        novel,
        "chapter":      ch_dict,
        "prev_chapter": dict(prev_ch._mapping) if prev_ch else None,
        "next_chapter": dict(next_ch._mapping) if next_ch else None,
    })


# ── JSON API routes ───────────────────────────────────────────────────────────

@router.get("/api/novels")
async def api_novels(
    sort: str = "popular",
    status: str = "",
    limit: int = Query(20, ge=1, le=100),
    page: int = Query(1, ge=1),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    conditions = ["1=1"]
    params: dict = {}
    if status:
        conditions.append("w.status = :status")
        params["status"] = status

    novels, total = await _fetch_works(
        session,
        where=" AND ".join(conditions),
        params=params,
        sort=sort,
        limit=limit,
        offset=(page - 1) * limit,
    )
    total_pages = max(1, (total + limit - 1) // limit)
    return JSONResponse({"novels": novels, "total": total, "page": page, "total_pages": total_pages})


@router.get("/api/search")
async def api_search(
    q: str = "",
    status: str = "",
    lang: str = "",
    sort: str = "popular",
    min_rating: float = 0,
    chap_min: int = 0,
    chap_max: int = 0,
    tags: str = "",
    exclude_tags: str = "",
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    conditions = ["1=1"]
    params: dict = {}

    if q:
        conditions.append("(w.title ILIKE :q OR w.synopsis ILIKE :q)")
        params["q"] = f"%{q}%"
    if status:
        conditions.append("w.status = :status")
        params["status"] = status
    if lang:
        conditions.append("w.original_language = :lang")
        params["lang"] = lang

    # Tag filtering via metadata_claims
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_list:
            # Works that have at least one matching tag claim
            tag_placeholders = ", ".join(f":tag_{i}" for i in range(len(tag_list)))
            conditions.append(f"""
                w.id IN (
                    SELECT DISTINCT v.work_id FROM metadata_claims mc
                    JOIN source_titles st ON st.id = mc.source_title_id
                    JOIN versions v ON v.id = st.version_id
                    WHERE mc.field_name IN ('tags', 'genres')
                      AND (
                          {' OR '.join(f"mc.normalised_value ILIKE :tag_{i}" for i in range(len(tag_list)))}
                      )
                )
            """)
            for i, t in enumerate(tag_list):
                params[f"tag_{i}"] = f"%{t}%"

    if exclude_tags:
        ex_list = [t.strip() for t in exclude_tags.split(",") if t.strip()]
        if ex_list:
            ex_placeholders = ", ".join(f":ex_{i}" for i in range(len(ex_list)))
            conditions.append(f"""
                w.id NOT IN (
                    SELECT DISTINCT v.work_id FROM metadata_claims mc
                    JOIN source_titles st ON st.id = mc.source_title_id
                    JOIN versions v ON v.id = st.version_id
                    WHERE mc.field_name IN ('tags', 'genres')
                      AND (
                          {' OR '.join(f"mc.normalised_value ILIKE :ex_{i}" for i in range(len(ex_list)))}
                      )
                )
            """)
            for i, t in enumerate(ex_list):
                params[f"ex_{i}"] = f"%{t}%"

    novels, total = await _fetch_works(
        session,
        where=" AND ".join(conditions),
        params=params,
        sort=sort,
        limit=limit,
        offset=(page - 1) * limit,
    )
    total_pages = max(1, (total + limit - 1) // limit)
    return JSONResponse({"novels": novels, "total": total, "page": page, "total_pages": total_pages})


@router.get("/api/stats")
async def api_stats(session: AsyncSession = Depends(get_session)) -> JSONResponse:
    novels = await session.scalar(select(func.count()).select_from(Work)) or 0
    chapters = await session.scalar(select(func.count()).select_from(VersionChapter)) or 0
    return JSONResponse({"novels": novels, "chapters": chapters})


@router.get("/api/novels/{work_id}/similar")
async def api_similar(
    work_id: str,
    limit: int = Query(12, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    # Find tag claims for this work
    tag_row = await session.execute(
        text("""
            SELECT COALESCE(STRING_AGG(mc.normalised_value, ','), '') AS tags
            FROM metadata_claims mc
            JOIN source_titles st ON st.id = mc.source_title_id
            JOIN versions v ON v.id = st.version_id
            WHERE v.work_id = :wid AND mc.field_name IN ('tags', 'genres') AND mc.is_resolved = true
        """),
        {"wid": work_id},
    )
    raw_tags = (tag_row.scalar_one_or_none() or "")
    tag_terms = [t.strip().lower() for t in re.split(r"[,;\|]+", raw_tags) if t.strip()]

    if not tag_terms:
        return JSONResponse({"novels": []})

    # Build query for works sharing any of these tags (excluding self)
    conditions = [f"w.id::text != :wid"]
    params: dict = {"wid": str(work_id)}
    or_clauses = " OR ".join(f"mc2.normalised_value ILIKE :t_{i}" for i in range(len(tag_terms)))
    for i, t in enumerate(tag_terms):
        params[f"t_{i}"] = f"%{t}%"

    sql = text(f"""
        SELECT {_WORK_SELECT}
        FROM works w
        WHERE w.id IN (
            SELECT DISTINCT v2.work_id
            FROM metadata_claims mc2
            JOIN source_titles st2 ON st2.id = mc2.source_title_id
            JOIN versions v2 ON v2.id = st2.version_id
            WHERE mc2.field_name IN ('tags', 'genres') AND ({or_clauses})
        ) AND {' AND '.join(conditions)}
        ORDER BY w.updated_at DESC NULLS LAST
        LIMIT :limit
    """)
    rows = (await session.execute(sql, {**params, "limit": limit})).fetchall()
    return JSONResponse({"novels": [_row_to_dict(r) for r in rows]})


@router.get("/api/novel/{slug}/chapters")
async def api_chapters(
    slug: str,
    limit: int = Query(500, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    work = await session.scalar(select(Work).where(Work.slug == slug))
    if not work:
        raise HTTPException(status_code=404, detail="Not found")

    rows = await session.execute(
        text("""
            SELECT vc.chapter_number AS chapter_num, vc.title
            FROM version_chapters vc
            JOIN versions v ON v.id = vc.version_id
            WHERE v.work_id = :wid
            ORDER BY vc.chapter_number ASC
            LIMIT :lim
        """),
        {"wid": work.id, "lim": limit},
    )
    chapters = [{"chapter_num": r.chapter_num, "title": r.title} for r in rows.fetchall()]
    return JSONResponse({"chapters": chapters})


@router.post("/api/library")
async def api_library_add(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


@router.delete("/api/library")
async def api_library_del(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


@router.post("/api/progress")
async def api_progress(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


@router.post("/api/novels/{work_id}/reviews")
async def api_review(work_id: str, request: Request) -> JSONResponse:
    # Reviews not yet implemented in v2 — return stub
    return JSONResponse({"ok": True, "stub": True})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _split_paragraphs(body: str) -> list[str]:
    if not body:
        return []
    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    if len(paras) > 1:
        return paras
    paras = [p.strip() for p in body.split("\n") if p.strip()]
    if len(paras) > 1:
        return paras
    # Sentence-boundary split as last resort
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z"\u201c])', body)
    if len(sentences) > 2:
        out = []
        for i in range(0, len(sentences), 3):
            p = " ".join(sentences[i:i + 3]).strip()
            if p:
                out.append(p)
        return out
    return [body.strip()] if body.strip() else []
