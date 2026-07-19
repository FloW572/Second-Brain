"""Document storage: metadata rows in the DB, file bytes on disk (named by row id).

Shared by the web dashboard and the Telegram bot so both store files the same way.
"""
import asyncio
import re
from pathlib import Path

# A #Projektname token selects/creates a project. It must be standalone (at the start
# or after whitespace) so a URL fragment like ".../p#section" or "C#" is NOT treated as
# a project; an optional space after # is allowed ("# Finanzen"). \w is Unicode in
# Python 3, so umlauts work (e.g. #Südtirol, #Urlaub-2026).
_HASHTAG_RE = re.compile(r"(?:^|\s)#[ \t]*(\w[\w-]*)")


def extract_project_hashtag(text: str | None) -> tuple[str | None, str]:
    """Pull the first standalone #Projektname (also '# Projektname') out of free text.

    Returns (project_name or None, text with that hashtag token removed and whitespace
    tidied). Shared by file captions and text capture so both use the same convention.
    """
    text = text or ""
    m = _HASHTAG_RE.search(text)
    if not m:
        return None, text.strip()
    cleaned = re.sub(r"\s+", " ", text[:m.start()] + " " + text[m.end():]).strip()
    return m.group(1), cleaned


def parse_caption(caption: str | None) -> tuple[str | None, str | None]:
    """Split a file caption into (project_name, note).

    The whole caption is the free-text note (location, event, ...). An optional
    #Projektname in it picks the project; that hashtag token is removed from the note.
    Returns (None, None) for an empty caption.
    """
    if not (caption or "").strip():
        return None, None
    project, note = extract_project_hashtag(caption)
    return project, (note or None)


def doc_path(docs_dir: str, doc_id: int) -> Path:
    return Path(docs_dir) / str(doc_id)


def human_size(n: int | None) -> str:
    size = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.0f} GB"


async def store_document(pool, docs_dir: str, project_id, filename: str,
                         content_type: str | None, content: bytes,
                         note: str | None = None) -> int:
    """Insert metadata, write the bytes to disk (as docs_dir/<id>), return the id."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO documents (project_id, filename, content_type, size_bytes, note) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (project_id, filename, content_type, len(content), note),
        )
        doc_id = (await cur.fetchone())[0]
        await conn.commit()
    path = doc_path(docs_dir, doc_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_bytes, content)
    return doc_id


async def list_documents(pool, project_id) -> list[dict]:
    """Documents for a project (project_id=None -> unassigned)."""
    where = "project_id IS NULL" if project_id is None else "project_id = %(pid)s"
    params = {} if project_id is None else {"pid": project_id}
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            f"SELECT id, filename, content_type, size_bytes, note FROM documents "
            f"WHERE {where} ORDER BY created_at DESC",
            params,
        )
        rows = await cur.fetchall()
    return [{"id": r[0], "filename": r[1], "content_type": r[2],
             "size_display": human_size(r[3]), "note": r[4]} for r in rows]


async def list_all_documents(pool) -> list[dict]:
    """Every document with its project name (project_id=None -> unassigned)."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT d.id, d.filename, d.content_type, d.size_bytes, d.project_id, p.name, d.note "
            "FROM documents d LEFT JOIN projects p ON p.id = d.project_id "
            "ORDER BY p.name NULLS FIRST, d.created_at DESC"
        )
        rows = await cur.fetchall()
    return [{"id": r[0], "filename": r[1], "content_type": r[2], "size_display": human_size(r[3]),
             "project_id": r[4], "project_name": r[5], "note": r[6]} for r in rows]


async def set_document_project(pool, doc_id: int, project_id: int | None) -> None:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("UPDATE documents SET project_id = %s WHERE id = %s", (project_id, doc_id))
        await conn.commit()


async def set_document_note(pool, doc_id: int, note: str | None) -> None:
    """Set/clear the free-text comment on a document (empty -> NULL)."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("UPDATE documents SET note = %s WHERE id = %s", (note, doc_id))
        await conn.commit()


async def get_document(pool, doc_id: int) -> dict | None:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT id, project_id, filename, content_type FROM documents WHERE id = %s",
            (doc_id,),
        )
        r = await cur.fetchone()
    if not r:
        return None
    return {"id": r[0], "project_id": r[1], "filename": r[2], "content_type": r[3]}


async def delete_document(pool, docs_dir: str, doc_id: int) -> bool:
    """Delete metadata + file. Returns True if a row existed."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("DELETE FROM documents WHERE id = %s RETURNING id", (doc_id,))
        found = await cur.fetchone() is not None
        await conn.commit()
    path = doc_path(docs_dir, doc_id)
    if path.exists():
        await asyncio.to_thread(path.unlink)
    return found
