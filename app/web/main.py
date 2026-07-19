"""FastAPI web dashboard: browse and manage the second brain in the browser.

Runs as its own service (see docker-compose) against the same database as the
bot. Mutations reuse the bot's tool handlers so validation, re-embedding and the
reminder reset stay identical across both interfaces.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.db import close_pool, init_pool
from app.documents import (
    delete_document,
    doc_path,
    get_document,
    list_all_documents,
    list_documents,
    set_document_note,
    set_document_project,
    store_document,
)
from app.query.tools import (
    _complete_item,
    _delete_item,
    _delete_project,
    _rename_project,
    _update_item,
)
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


async def _project_name(pid: int) -> str | None:
    async with _pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("SELECT name FROM projects WHERE id = %s", (pid,))
        row = await cur.fetchone()
    return row[0] if row else None


@app.get("/")
async def index(request: Request, type: str = "", q: str = "", project: str = ""):
    project_name = None
    project_id = None
    documents: list[dict] = []
    if q:
        hits = await hybrid_search(_pool, settings, q, None, 30)
        ids = [h["id"] for h in hits]
        items = await _fetch("WHERE i.id = ANY(%(ids)s)", {"ids": ids}) if ids else []
    elif project == "none":
        items = await _fetch("WHERE i.project_id IS NULL")
        project_name = "Ohne Projekt"
        documents = await list_documents(_pool, None)
    elif project.isdigit():
        project_id = int(project)
        items = await _fetch("WHERE i.project_id = %(pid)s", {"pid": project_id})
        project_name = await _project_name(project_id)
        documents = await list_documents(_pool, project_id)
    elif type in TYPE_EMOJI:
        items = await _fetch("WHERE i.type = %(type)s", {"type": type})
    else:
        items = await _fetch()
    return templates.TemplateResponse(
        request=request, name="index.html",
        context={"items": items, "active_type": type, "q": q,
                 "project_name": project_name, "project_id": project_id,
                 "documents": documents, "type_emoji": TYPE_EMOJI},
    )


@app.post("/projects/{pid}/documents")
async def upload_document(pid: int, file: UploadFile = File(...), note: str = Form("")):
    content = await file.read()
    if content:
        await store_document(_pool, settings.docs_dir, pid,
                             file.filename or "dokument", file.content_type, content,
                             note=note.strip() or None)
    return RedirectResponse(f"/?project={pid}", status_code=303)


@app.get("/documents/{doc_id}")
async def download_document(doc_id: int):
    meta = await get_document(_pool, doc_id)
    if not meta:
        return RedirectResponse("/", status_code=303)
    path = doc_path(settings.docs_dir, doc_id)
    if not path.exists():
        return RedirectResponse("/", status_code=303)
    return FileResponse(path, filename=meta["filename"],
                        media_type=meta["content_type"] or "application/octet-stream")


@app.post("/documents/{doc_id}/delete")
async def remove_document(doc_id: int):
    meta = await get_document(_pool, doc_id)
    await delete_document(_pool, settings.docs_dir, doc_id)
    pid = meta["project_id"] if meta else None
    return RedirectResponse(f"/?project={pid}" if pid else "/?project=none", status_code=303)


async def _all_projects() -> list[dict]:
    async with _pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id, name FROM projects WHERE status <> 'archived' ORDER BY name")
        return [{"id": r[0], "name": r[1]} for r in await cur.fetchall()]


@app.get("/documents")
async def documents_view(request: Request):
    return templates.TemplateResponse(
        request=request, name="documents.html",
        context={"documents": await list_all_documents(_pool), "projects": await _all_projects()},
    )


@app.post("/documents/{doc_id}/project")
async def move_document(doc_id: int, project: str = Form("none")):
    await set_document_project(_pool, doc_id, int(project) if project.isdigit() else None)
    return RedirectResponse("/documents", status_code=303)


def _safe_back(back: str) -> str:
    """Only allow relative in-app redirect targets (avoid open redirects)."""
    return back if back.startswith("/") and not back.startswith("//") else "/"


@app.post("/documents/{doc_id}/note")
async def edit_document_note(doc_id: int, note: str = Form(""), back: str = Form("/")):
    await set_document_note(_pool, doc_id, note.strip() or None)
    return RedirectResponse(_safe_back(back), status_code=303)


@app.get("/projects")
async def projects_view(request: Request):
    async with _pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT p.id, p.name, p.description,
                   count(i.id) AS total,
                   count(i.id) FILTER (WHERE i.type = 'todo' AND i.status <> 'done') AS open_todos,
                   (SELECT count(*) FROM documents d WHERE d.project_id = p.id) AS docs
            FROM projects p LEFT JOIN items i ON i.project_id = p.id
            WHERE p.status <> 'archived'
            GROUP BY p.id ORDER BY p.name
            """
        )
        projects = [
            {"id": r[0], "name": r[1], "description": r[2], "total": r[3],
             "open_todos": r[4], "docs": r[5]}
            for r in await cur.fetchall()
        ]
        await cur.execute("SELECT count(*) FROM items WHERE project_id IS NULL")
        no_project = (await cur.fetchone())[0]
    return templates.TemplateResponse(
        request=request, name="projects.html",
        context={"projects": projects, "no_project": no_project},
    )


@app.post("/projects/{pid}/rename")
async def rename_project(pid: int, new_name: str = Form("")):
    # Reuses the bot's handler (rename by exact id); it no-ops on a blank name
    # or a clash with another project.
    if new_name.strip():
        await _rename_project(_pool, settings, {"id": pid, "new_name": new_name.strip()})
    return RedirectResponse("/projects", status_code=303)


@app.post("/projects/{pid}/delete")
async def delete_project(pid: int):
    # Reuses the bot's handler: it refuses unless the project is truly empty
    # (no items, no files), so a non-empty project simply stays put.
    await _delete_project(_pool, settings, {"id": pid})
    return RedirectResponse("/projects", status_code=303)


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
