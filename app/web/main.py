"""FastAPI web dashboard: browse and manage the second brain in the browser.

Runs as its own service (see docker-compose) against the same database as the
bot. Mutations reuse the bot's tool handlers so validation, re-embedding and the
reminder reset stay identical across both interfaces.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.db import close_pool, init_pool
from app.query.tools import _complete_item, _delete_item, _update_item
from app.search import hybrid_search

logger = logging.getLogger(__name__)
settings = get_settings()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

TYPE_EMOJI = {"todo": "✅", "idea": "💡", "note": "📝", "reference": "🔗"}
PRIORITY_LABEL = {1: "hoch", 2: "mittel", 3: "niedrig"}

_pool = None

_BASE_SELECT = """
    SELECT i.id, i.type, i.title, i.content, i.status, i.priority, i.due_at, i.tags, p.name
    FROM items i LEFT JOIN projects p ON p.id = i.project_id
"""
_ORDER = """
    ORDER BY (i.type = 'todo' AND i.status IS DISTINCT FROM 'done') DESC,
             i.due_at ASC NULLS LAST, i.priority ASC NULLS LAST, i.created_at DESC
"""


@asynccontextmanager
async def lifespan(_app):
    global _pool
    _pool = await init_pool(settings.database_url)
    yield
    await close_pool()


app = FastAPI(title="Second Brain Dashboard", lifespan=lifespan)


def _row_to_item(r) -> dict:
    due = r[6]
    return {
        "id": r[0], "type": r[1], "emoji": TYPE_EMOJI.get(r[1], "📝"),
        "title": r[2], "content": r[3], "status": r[4],
        "priority": r[5], "priority_label": PRIORITY_LABEL.get(r[5]),
        "due_display": due.strftime("%d.%m.%Y %H:%M") if due else "",
        "due_value": due.strftime("%Y-%m-%dT%H:%M") if due else "",
        "tags": list(r[7] or []), "project": r[8],
    }


async def _fetch(where: str = "", params: dict | None = None) -> list[dict]:
    async with _pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(_BASE_SELECT + where + _ORDER, params or {})
        return [_row_to_item(r) for r in await cur.fetchall()]


@app.get("/")
async def index(request: Request, type: str = "", q: str = ""):
    if q:
        hits = await hybrid_search(_pool, settings, q, None, 30)
        ids = [h["id"] for h in hits]
        items = await _fetch("WHERE i.id = ANY(%(ids)s)", {"ids": ids}) if ids else []
    elif type in TYPE_EMOJI:
        items = await _fetch("WHERE i.type = %(type)s", {"type": type})
    else:
        items = await _fetch()
    return templates.TemplateResponse(
        request=request, name="index.html",
        context={"items": items, "active_type": type, "q": q, "type_emoji": TYPE_EMOJI},
    )


@app.get("/edit/{item_id}")
async def edit_form(request: Request, item_id: int):
    rows = await _fetch("WHERE i.id = %(id)s", {"id": item_id})
    if not rows:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request=request, name="edit.html",
        context={"item": rows[0], "type_emoji": TYPE_EMOJI},
    )


@app.post("/edit/{item_id}")
async def edit_apply(item_id: int, title: str = Form(...), type: str = Form(...),
                     content: str = Form(""), status: str = Form(""),
                     priority: str = Form(""), due_at: str = Form(""),
                     project: str = Form(""), tags: str = Form("")):
    args = {
        "id": item_id,
        "title": title,
        "type": type,
        "content": content.strip() or None,
        "priority": int(priority) if priority else None,
        "due_at": due_at or None,
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
    }
    if status:
        args["status"] = status
    if project.strip():
        args["project"] = project.strip()
    await _update_item(_pool, settings, args)
    return RedirectResponse("/", status_code=303)


@app.post("/complete/{item_id}")
async def complete(item_id: int):
    await _complete_item(_pool, settings, {"id": item_id})
    return RedirectResponse("/", status_code=303)


@app.post("/delete/{item_id}")
async def delete(item_id: int):
    await _delete_item(_pool, settings, {"id": item_id})
    return RedirectResponse("/", status_code=303)
