"""Document storage: metadata rows in the DB, file bytes on disk (named by row id).

Shared by the web dashboard and the Telegram bot so both store files the same way.
"""
import asyncio
from pathlib import Path


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
                         content_type: str | None, content: bytes) -> int:
    """Insert metadata, write the bytes to disk (as docs_dir/<id>), return the id."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO documents (project_id, filename, content_type, size_bytes) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (project_id, filename, content_type, len(content)),
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
            f"SELECT id, filename, content_type, size_bytes FROM documents "
            f"WHERE {where} ORDER BY created_at DESC",
            params,
        )
        rows = await cur.fetchall()
    return [{"id": r[0], "filename": r[1], "content_type": r[2],
             "size_display": human_size(r[3])} for r in rows]


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
