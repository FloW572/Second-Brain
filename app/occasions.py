"""Wiederkehrende jährliche Anlässe (Geburtstage, Jahrestage, ...).

Ein Anlass ist bewusst KEIN Todo: er hat kein Jahr, sondern nur Tag+Monat, und
wiederholt sich von selbst. Die nächste Wiederholung wird aus (month, day) gegen
das heutige Datum berechnet; erinnert wird ``lead_days`` im Voraus, damit noch
Zeit bleibt, ein Geschenk zu besorgen oder etwas zu planen.

Die Datumslogik hier ist bewusst frei von DB- und Anthropic-Abhängigkeiten
(stdlib only), damit sie direkt testbar ist. Die versendenden Loops liegen in
``app.nudges``.
"""
import calendar
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

KINDS = ("birthday", "anniversary", "custom")

KIND_LABEL = {
    "birthday": "Geburtstag",
    "anniversary": "Jahrestag",
    "custom": "Anlass",
}


def clamp_day(year: int, month: int, day: int) -> date:
    """Tag/Monat auf ein konkretes Jahr legen. 29.2. fällt in Nicht-Schaltjahren auf den 28.2."""
    if month == 2 and day == 29 and not calendar.isleap(year):
        day = 28
    return date(year, month, day)


def next_occurrence(month: int, day: int, today: date) -> date:
    """Nächstes Vorkommen des Anlasses — heute zählt noch als 'kommt'."""
    this_year = clamp_day(today.year, month, day)
    return this_year if this_year >= today else clamp_day(today.year + 1, month, day)


def days_until(month: int, day: int, today: date) -> int:
    return (next_occurrence(month, day, today) - today).days


def is_due(month: int, day: int, lead_days: int,
           last_notified_on: date | None, today: date) -> bool:
    """Soll für diesen Anlass JETZT eine Vorlauf-Erinnerung raus?

    Genau einmal pro Wiederholung: sobald das Vorlauffenster begonnen hat und in
    diesem Fenster noch nicht erinnert wurde.
    """
    occurrence = next_occurrence(month, day, today)
    if (occurrence - today).days > lead_days:
        return False
    window_start = occurrence - timedelta(days=lead_days)
    return last_notified_on is None or last_notified_on < window_start


def _row_to_occasion(row, today: date) -> dict:
    (oid, label, person, kind, month, day, lead_days, notes, last_notified_on, project) = row
    return {
        "id": oid, "label": label, "person": person, "kind": kind,
        "month": month, "day": day, "lead_days": lead_days, "notes": notes,
        "last_notified_on": last_notified_on, "project": project,
        "next_date": next_occurrence(month, day, today).isoformat(),
        "days_until": days_until(month, day, today),
    }


_SELECT = """
    SELECT o.id, o.label, o.person, o.kind, o.month, o.day, o.lead_days,
           o.notes, o.last_notified_on, p.name
    FROM occasions o LEFT JOIN projects p ON p.id = o.project_id
"""


async def list_occasions(pool, today: date, limit: int = 50) -> list[dict]:
    """Alle Anlässe, nach zeitlicher Nähe sortiert (der nächste zuerst)."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(_SELECT + " ORDER BY o.month, o.day")
        rows = await cur.fetchall()
    occasions = [_row_to_occasion(r, today) for r in rows]
    occasions.sort(key=lambda o: o["days_until"])
    return occasions[:limit]


async def due_occasions(pool, today: date) -> list[dict]:
    """Anlässe, deren Vorlauffenster erreicht ist und die noch nicht erinnert wurden."""
    return [o for o in await list_occasions(pool, today, limit=1000)
            if is_due(o["month"], o["day"], o["lead_days"], o["last_notified_on"], today)]


async def add_occasion(pool, label: str, month: int, day: int, *, person: str | None = None,
                       kind: str = "birthday", lead_days: int = 14,
                       notes: str | None = None, project_id: int | None = None) -> dict:
    """Anlass anlegen oder — bei gleichem Label — aktualisieren, statt zu duplizieren."""
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return {"added": False, "reason": "month must be 1-12 and day 1-31"}
    if kind not in KINDS:
        kind = "custom"

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM occasions WHERE label ILIKE %s LIMIT 1", (label,))
            existing = await cur.fetchone()
            if existing:
                await cur.execute(
                    """
                    UPDATE occasions
                    SET month = %s, day = %s, person = COALESCE(%s, person), kind = %s,
                        lead_days = %s, notes = COALESCE(%s, notes),
                        project_id = COALESCE(%s, project_id), last_notified_on = NULL
                    WHERE id = %s
                    RETURNING id
                    """,
                    (month, day, person, kind, lead_days, notes, project_id, existing[0]),
                )
            else:
                await cur.execute(
                    """
                    INSERT INTO occasions
                        (label, person, kind, month, day, lead_days, notes, project_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (label, person, kind, month, day, lead_days, notes, project_id),
                )
            occasion_id = (await cur.fetchone())[0]
        await conn.commit()

    today = date.today()
    return {"added": True, "updated": bool(existing), "id": occasion_id, "label": label,
            "next_date": next_occurrence(month, day, today).isoformat(),
            "days_until": days_until(month, day, today)}


async def get_occasion(pool, occasion_id: int, today: date) -> dict | None:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(_SELECT + " WHERE o.id = %s", (occasion_id,))
        row = await cur.fetchone()
    return _row_to_occasion(row, today) if row else None


async def update_occasion(pool, occasion_id: int, *, label: str | None = None,
                          person: str | None = None, kind: str | None = None,
                          month: int | None = None, day: int | None = None,
                          lead_days: int | None = None, notes: str | None = None,
                          project_id: int | None = None) -> dict:
    """Update an occasion in place by id (unlike add_occasion, which upserts by label —
    not useful here since editing may itself change the label)."""
    if month is not None and not 1 <= month <= 12:
        return {"updated": False, "reason": "month must be 1-12"}
    if day is not None and not 1 <= day <= 31:
        return {"updated": False, "reason": "day must be 1-31"}
    if kind is not None and kind not in KINDS:
        kind = "custom"

    sets: list[str] = []
    params: list = []
    for column, value in (("label", label), ("person", person), ("kind", kind),
                          ("month", month), ("day", day), ("lead_days", lead_days),
                          ("notes", notes), ("project_id", project_id)):
        if value is not None:
            sets.append(f"{column} = %s")
            params.append(value)
    if month is not None or day is not None:
        # The date moved — clear so a fresh lead-time reminder can fire for it.
        sets.append("last_notified_on = NULL")
    if not sets:
        return {"updated": False, "reason": "no fields to update"}

    params.append(occasion_id)
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            f"UPDATE occasions SET {', '.join(sets)} WHERE id = %s RETURNING label",
            params,
        )
        row = await cur.fetchone()
        await conn.commit()
    if not row:
        return {"updated": False, "reason": "not found"}
    return {"updated": True, "id": occasion_id, "label": row[0]}


async def delete_occasion(pool, occasion_id: int) -> dict:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("DELETE FROM occasions WHERE id = %s RETURNING label", (occasion_id,))
        row = await cur.fetchone()
        await conn.commit()
    if row:
        return {"deleted": True, "id": occasion_id, "label": row[0]}
    return {"deleted": False, "id": occasion_id, "reason": "not found"}


async def mark_notified(pool, occasion_id: int, today: date) -> None:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("UPDATE occasions SET last_notified_on = %s WHERE id = %s",
                          (today, occasion_id))
        await conn.commit()


def format_occasion(occasion: dict) -> str:
    """Eine Zeile für Telegram: '🎂 #3 Luisa Geburtstag · 17.05. · in 12 Tagen'."""
    emoji = {"birthday": "🎂", "anniversary": "💞"}.get(occasion["kind"], "📌")
    left = occasion["days_until"]
    when = "heute" if left == 0 else ("morgen" if left == 1 else f"in {left} Tagen")
    return (f'{emoji} #{occasion["id"]} {occasion["label"]} · '
            f'{occasion["day"]:02d}.{occasion["month"]:02d}. · {when}')
