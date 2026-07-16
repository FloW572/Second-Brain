"""Resolve a free-text project hint to an existing project, or create one."""
import logging

logger = logging.getLogger(__name__)


async def resolve_project(conn, project_hint: str | None,
                          create_if_missing: bool = True) -> tuple[int | None, str | None]:
    """Return (project_id, project_name) for the hint, creating the project if needed."""
    if not project_hint:
        return None, None

    async with conn.cursor() as cur:
        # 1) exact-ish match
        await cur.execute(
            "SELECT id, name FROM projects "
            "WHERE name ILIKE %s AND status <> 'archived' ORDER BY id LIMIT 1",
            (project_hint,),
        )
        row = await cur.fetchone()
        if row:
            return row[0], row[1]

        # 2) fuzzy contains (either direction)
        await cur.execute(
            "SELECT id, name FROM projects "
            "WHERE (name ILIKE %s OR %s ILIKE ('%%' || name || '%%')) "
            "AND status <> 'archived' ORDER BY id LIMIT 1",
            (f"%{project_hint}%", project_hint),
        )
        row = await cur.fetchone()
        if row:
            return row[0], row[1]

        # 3) create
        if create_if_missing:
            await cur.execute(
                "INSERT INTO projects (name) VALUES (%s) RETURNING id, name",
                (project_hint,),
            )
            row = await cur.fetchone()
            logger.info("Created project %r (id=%s)", row[1], row[0])
            return row[0], row[1]

    return None, None
