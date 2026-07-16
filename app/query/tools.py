"""Tools the query agent (Claude) can call to inspect the second brain."""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

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
                                    "enum": ["todo", "idea", "note", "reference"]}},
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


_DISPATCH = {
    "now": _now,
    "list_projects": _list_projects,
    "list_todos": _list_todos,
    "search": _search,
    "complete_item": _complete_item,
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
