"""Tools the query agent (Claude) can call to inspect the second brain."""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.ingest.embed import embed_text, to_vector_literal
from app.ingest.projects import resolve_project
from app.models import ITEM_TYPES
from app.search import hybrid_search

logger = logging.getLogger(__name__)

TOOLS = [
    {
        "name": "now",
        "description": "Current date/time. Call before reasoning about due dates.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_projects",
        "description": "List active projects with their open-todo counts.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_todos",
        "description": "List todos, ordered by due date then priority.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["open", "doing", "done", "all"],
                           "description": "Default 'open'."},
                "due_before": {"type": "string", "description": "ISO date; only todos due on/before."},
                "project": {"type": "string", "description": "Filter by project name (partial)."},
                "priority": {"type": "integer", "enum": [1, 2, 3]},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "search",
        "description": "Hybrid semantic + keyword search across all items (todos, ideas, notes).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "types": {"type": "array",
                          "items": {"type": "string",
                                    "enum": list(ITEM_TYPES)}},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "complete_item",
        "description": "Mark a todo as done by its id.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        },
    },
    {
        "name": "update_item",
        "description": "Update fields of an existing item by id. Only the fields you pass are "
                       "changed; omit the rest. Use this to rename, reschedule, reprioritise, "
                       "move to a project, or change status/tags of a todo/idea/note.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "The item id to update."},
                "title": {"type": "string", "description": "New title."},
                "content": {"type": ["string", "null"], "description": "New content, or null to clear."},
                "due_date": {"type": ["string", "null"],
                             "description": "New due date as ISO YYYY-MM-DD, or null to clear."},
                "priority": {"type": ["integer", "null"],
                             "description": "1 = high, 2 = medium, 3 = low, or null to clear."},
                "status": {"type": "string", "enum": ["open", "doing", "done"],
                           "description": "Todo status."},
                "project": {"type": "string",
                            "description": "Project name; created if it does not exist yet."},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["id"],
        },
    },
    {
        "name": "delete_item",
        "description": "Permanently delete an item by id. This cannot be undone. If more than one "
                       "item could be meant, confirm the exact id with the user before deleting.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "The item id to delete."}},
            "required": ["id"],
        },
    },
]


async def _now(pool, settings, args):
    dt = datetime.now(ZoneInfo(settings.timezone))
    return {"datetime": dt.isoformat(timespec="minutes"),
            "date": dt.date().isoformat(),
            "weekday": dt.strftime("%A"),
            "timezone": settings.timezone}


async def _list_projects(pool, settings, args):
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT p.id, p.name, p.status, p.description,
                   count(i.*) FILTER (WHERE i.type = 'todo' AND i.status = 'open') AS open_todos
            FROM projects p
            LEFT JOIN items i ON i.project_id = p.id
            WHERE p.status <> 'archived'
            GROUP BY p.id ORDER BY p.name
            """
        )
        rows = await cur.fetchall()
    return {"projects": [
        {"id": r[0], "name": r[1], "status": r[2], "description": r[3], "open_todos": r[4]}
        for r in rows
    ]}


async def _list_todos(pool, settings, args):
    where = ["i.type = 'todo'"]
    params: list = []
    status = args.get("status", "open")
    if status and status != "all":
        where.append("i.status = %s")
        params.append(status)
    if args.get("due_before"):
        where.append("i.due_date <= %s")
        params.append(args["due_before"])
    if args.get("project"):
        where.append("p.name ILIKE %s")
        params.append(f"%{args['project']}%")
    if args.get("priority"):
        where.append("i.priority = %s")
        params.append(args["priority"])
    limit = int(args.get("limit", 50))

    sql = f"""
        SELECT i.id, i.title, i.status, i.priority, i.due_date, i.tags, p.name
        FROM items i LEFT JOIN projects p ON p.id = i.project_id
        WHERE {' AND '.join(where)}
        ORDER BY i.due_date ASC NULLS LAST, i.priority ASC NULLS LAST, i.created_at ASC
        LIMIT {limit}
    """
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()
    return {"todos": [
        {"id": r[0], "title": r[1], "status": r[2], "priority": r[3],
         "due_date": r[4].isoformat() if r[4] else None,
         "tags": list(r[5] or []), "project": r[6]}
        for r in rows
    ]}


async def _search(pool, settings, args):
    results = await hybrid_search(
        pool, settings, args["query"], args.get("types"), int(args.get("limit", 8))
    )
    return {"results": results}


async def _complete_item(pool, settings, args):
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "UPDATE items SET status = 'done' WHERE id = %s AND type = 'todo' RETURNING title",
            (args["id"],),
        )
        row = await cur.fetchone()
        await conn.commit()
    if row:
        return {"completed": True, "id": args["id"], "title": row[0]}
    return {"completed": False, "id": args["id"], "reason": "not found or not a todo"}


async def _update_item(pool, settings, args):
    item_id = args.get("id")
    if not item_id:
        return {"updated": False, "reason": "no id given"}

    sets: list[str] = []
    params: list = []

    if args.get("title"):
        sets.append("title = %s")
        params.append(str(args["title"]).strip()[:200])
    if "content" in args:
        sets.append("content = %s")
        params.append(args["content"])
    if "due_date" in args:
        sets.append("due_date = %s")
        params.append(args["due_date"] or None)
    if "priority" in args:
        prio = args["priority"]
        if prio is not None and prio not in (1, 2, 3):
            return {"updated": False, "reason": "priority must be 1, 2, 3 or null"}
        sets.append("priority = %s")
        params.append(prio)
    if args.get("status"):
        if args["status"] not in ("open", "doing", "done"):
            return {"updated": False, "reason": "status must be open, doing or done"}
        sets.append("status = %s")
        params.append(args["status"])
    if args.get("tags") is not None:
        sets.append("tags = %s")
        params.append([t.strip() for t in args["tags"] if isinstance(t, str) and t.strip()])

    async with pool.connection() as conn:
        # A project name is resolved to an id (creating the project if needed).
        if args.get("project"):
            project_id, _ = await resolve_project(conn, args["project"])
            sets.append("project_id = %s")
            params.append(project_id)

        # If the searchable text changed, re-embed so semantic search stays accurate.
        if args.get("title") or "content" in args:
            async with conn.cursor() as cur:
                await cur.execute("SELECT title, content FROM items WHERE id = %s", (item_id,))
                current = await cur.fetchone()
            if current is None:
                return {"updated": False, "id": item_id, "reason": "not found"}
            new_title = str(args["title"]).strip()[:200] if args.get("title") else current[0]
            new_content = args["content"] if "content" in args else current[1]
            emb = to_vector_literal(
                await embed_text(f"{new_title}\n{new_content or ''}", settings.embedding_model)
            )
            sets.append("embedding = %s::vector")
            params.append(emb)

        if not sets:
            return {"updated": False, "id": item_id, "reason": "no fields to update"}

        params.append(item_id)
        async with conn.cursor() as cur:
            await cur.execute(
                f"UPDATE items SET {', '.join(sets)} WHERE id = %s RETURNING title, type",
                params,
            )
            row = await cur.fetchone()
        await conn.commit()

    if row:
        return {"updated": True, "id": item_id, "title": row[0], "type": row[1]}
    return {"updated": False, "id": item_id, "reason": "not found"}


async def _delete_item(pool, settings, args):
    item_id = args.get("id")
    if not item_id:
        return {"deleted": False, "reason": "no id given"}
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("DELETE FROM items WHERE id = %s RETURNING title, type", (item_id,))
        row = await cur.fetchone()
        await conn.commit()
    if row:
        return {"deleted": True, "id": item_id, "title": row[0], "type": row[1]}
    return {"deleted": False, "id": item_id, "reason": "not found"}


_DISPATCH = {
    "now": _now,
    "list_projects": _list_projects,
    "list_todos": _list_todos,
    "search": _search,
    "complete_item": _complete_item,
    "update_item": _update_item,
    "delete_item": _delete_item,
}


async def run_tool(pool, settings, name: str, tool_input: dict) -> dict:
    handler = _DISPATCH.get(name)
    if handler is None:
        return {"error": f"unknown tool {name}"}
    try:
        return await handler(pool, settings, tool_input or {})
    except Exception as exc:  # noqa: BLE001 - surface as tool error to the model
        logger.exception("tool %s failed", name)
        return {"error": f"{type(exc).__name__}: {exc}"}
