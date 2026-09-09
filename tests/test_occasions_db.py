"""Integrationstests für die Anlass- und Ideen-Queries gegen ein echtes Postgres.

Die übrigen Tests laufen bewusst ohne Datenbank; sie prüfen reine Logik. Damit bleibt
aber ungetestet, was nur die DB beantworten kann: Spaltenreihenfolge im SELECT, Upsert,
`make_interval`, und das Zusammenspiel mit dem `set_updated_at()`-Trigger. Genau dort
saß der Fehler, den `migrations/007` behebt.

Diese Datei überspringt sich, solange ``TEST_DATABASE_URL`` nicht gesetzt ist — die CI
bleibt dadurch datenbankfrei. Zum Ausführen siehe README ("Tests").

Alle Testdaten tragen das Präfix ``IT-TEST``; aufgeräumt wird ausschließlich danach, damit
ein versehentlicher Lauf gegen eine befüllte Datenbank nichts anderes anfasst.
"""
import asyncio
import os
from datetime import date

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL nicht gesetzt — Integrationstests übersprungen",
)

if TEST_DATABASE_URL:                       # sonst fehlen die Abhängigkeiten in der CI
    from psycopg_pool import AsyncConnectionPool

    from app.nudges import _dormant_ideas, _mark_nudged
    from app.occasions import (add_occasion, delete_occasion, due_occasions,
                               list_occasions, mark_notified)

PREFIX = "IT-TEST"
CONNECT_TIMEOUT_SECONDS = 5
_unreachable: list[str] = []      # gemerkte Fehlermeldung, siehe run()


def run(main):
    """Öffnet einen Pool, räumt vor und nach dem Test auf und fährt die Coroutine."""
    async def _run():
        pool = AsyncConnectionPool(TEST_DATABASE_URL, min_size=1, max_size=2, open=False,
                                   timeout=CONNECT_TIMEOUT_SECONDS)
        # wait=True: eine nicht erreichbare Datenbank soll hier mit einer klaren Meldung
        # scheitern, statt den Testlauf minutenlang auf Reconnects warten zu lassen.
        # Der erste Fehlschlag wird gemerkt, damit nicht jeder weitere Test erneut wartet.
        if _unreachable:
            pytest.fail(_unreachable[0])
        try:
            await pool.open(wait=True, timeout=CONNECT_TIMEOUT_SECONDS)
        except Exception as exc:
            await pool.close()
            _unreachable.append(f"TEST_DATABASE_URL ist gesetzt, aber die Datenbank ist "
                                f"nicht erreichbar: {exc}")
            pytest.fail(_unreachable[0])
        try:
            await _cleanup(pool)
            return await main(pool)
        finally:
            await _cleanup(pool)
            await pool.close()
    return asyncio.run(_run())


def _mine(rows):
    """Nur die Zeilen dieses Tests.

    Die Query-Funktionen liefern alles, was in der Datenbank steht. Ohne diesen Filter
    würde ein Test gegen eine befüllte Datenbank fremde Einträge prüfen — und, schlimmer,
    ein `_mark_nudged` darauf schreiben. Deshalb IMMER filtern, bevor eine Zeile
    weiterverwendet wird.
    """
    return [r for r in rows if str(r.get("title") or r.get("label") or "").startswith(PREFIX)]


async def _cleanup(pool):
    async with pool.connection() as conn, conn.cursor() as cur:
        # ILIKE, damit auch eine im Test veränderte Schreibweise sicher mit aufgeräumt wird
        await cur.execute("DELETE FROM occasions WHERE label ILIKE %s", (f"{PREFIX}%",))
        await cur.execute("DELETE FROM items WHERE title ILIKE %s", (f"{PREFIX}%",))
        await cur.execute("DELETE FROM projects WHERE name ILIKE %s", (f"{PREFIX}%",))
        await conn.commit()


async def _seed_birthday(pool, day=10, month=6, lead_days=14):
    return await add_occasion(pool, f"{PREFIX} Geburtstag", month, day,
                              person=f"{PREFIX} Person", kind="birthday",
                              lead_days=lead_days)


# --- Anlegen und Auslesen ---------------------------------------------------

def test_occasion_roundtrip_maps_every_field():
    async def main(pool):
        await _seed_birthday(pool)
        found = [o for o in await list_occasions(pool, date(2026, 5, 27))
                 if o["label"].startswith(PREFIX)]
        assert len(found) == 1
        return found[0]

    occasion = run(main)
    assert occasion["month"] == 6
    assert occasion["day"] == 10
    assert occasion["lead_days"] == 14
    assert occasion["person"] == f"{PREFIX} Person"
    assert occasion["kind"] == "birthday"
    assert occasion["next_date"] == "2026-06-10"
    assert occasion["days_until"] == 14


def test_project_is_resolved_through_the_join():
    async def main(pool):
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("INSERT INTO projects (name) VALUES (%s) RETURNING id",
                              (f"{PREFIX} Projekt",))
            project_id = (await cur.fetchone())[0]
            await conn.commit()
        await add_occasion(pool, f"{PREFIX} Mit Projekt", 3, 1, project_id=project_id)
        return [o for o in await list_occasions(pool, date(2026, 1, 1))
                if o["label"] == f"{PREFIX} Mit Projekt"][0]

    assert run(main)["project"] == f"{PREFIX} Projekt"


def test_same_label_updates_instead_of_duplicating():
    async def main(pool):
        await _seed_birthday(pool)
        # andere Schreibweise: das Label wird per ILIKE gematcht
        result = await add_occasion(pool, f"{PREFIX} geburtstag".lower(), 6, 11, lead_days=21)
        found = [o for o in await list_occasions(pool, date(2026, 5, 27))
                 if o["label"].startswith(PREFIX)]
        return result, found

    result, found = run(main)
    assert result["updated"] is True
    assert len(found) == 1, "Label-Treffer darf keinen zweiten Anlass anlegen"
    assert (found[0]["month"], found[0]["day"]) == (6, 11)
    assert found[0]["lead_days"] == 21
    assert found[0]["person"] == f"{PREFIX} Person", "person darf nicht verloren gehen"


def test_delete_reports_unknown_id():
    async def main(pool):
        created = await _seed_birthday(pool)
        return await delete_occasion(pool, created["id"]), await delete_occasion(pool, 2 ** 30)

    deleted, missing = run(main)
    assert deleted["deleted"] is True
    assert missing["deleted"] is False


def test_occasion_survives_deletion_of_its_project():
    async def main(pool):
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("INSERT INTO projects (name) VALUES (%s) RETURNING id",
                              (f"{PREFIX} Projekt",))
            project_id = (await cur.fetchone())[0]
            await conn.commit()
        await add_occasion(pool, f"{PREFIX} Mit Projekt", 3, 1, project_id=project_id)
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            await conn.commit()
        return [o for o in await list_occasions(pool, date(2026, 1, 1))
                if o["label"] == f"{PREFIX} Mit Projekt"]

    remaining = run(main)
    assert len(remaining) == 1, "ON DELETE SET NULL darf den Anlass nicht mitnehmen"
    assert remaining[0]["project"] is None


# --- Fälligkeit über den Jahreslauf -----------------------------------------

def test_reminder_fires_once_per_year():
    async def main(pool):
        created = await _seed_birthday(pool)

        too_early = _mine(await due_occasions(pool, date(2026, 5, 26)))
        on_time = _mine(await due_occasions(pool, date(2026, 5, 27)))
        await mark_notified(pool, created["id"], date(2026, 5, 27))
        after = _mine(await due_occasions(pool, date(2026, 5, 30)))
        on_the_day = _mine(await due_occasions(pool, date(2026, 6, 10)))
        next_year = _mine(await due_occasions(pool, date(2027, 5, 27)))
        return too_early, on_time, after, on_the_day, next_year

    too_early, on_time, after, on_the_day, next_year = run(main)
    assert too_early == [], "15 Tage vorher ist das Vorlauffenster noch zu"
    assert len(on_time) == 1, "genau lead_days vorher muss erinnert werden"
    assert after == [], "im selben Fenster darf nicht erneut erinnert werden"
    assert on_the_day == [], "auch am Tag selbst nicht erneut"
    assert len(next_year) == 1, "im Folgejahr muss der Anlass wieder auflaufen"


# --- Ideen-Auffrischung ------------------------------------------------------

async def _seed_ideas(pool):
    async with pool.connection() as conn, conn.cursor() as cur:
        # updated_at direkt beim INSERT setzen — der Trigger greift nur BEFORE UPDATE.
        await cur.execute(
            "INSERT INTO items (type, title, content, updated_at) VALUES "
            "(%s, %s, %s, now() - interval '120 days'), "
            "(%s, %s, NULL, now() - interval '2 days'), "
            "(%s, %s, NULL, now() - interval '200 days')",
            ("idea", f"{PREFIX} Alte Idee", "Salzkammergut",
             "idea", f"{PREFIX} Frische Idee",
             "todo", f"{PREFIX} Todo"),
        )
        await conn.commit()


def test_only_dormant_ideas_are_resurfaced():
    async def main(pool):
        await _seed_ideas(pool)
        return await _dormant_ideas(pool, 30, 90, 10)

    ideas = _mine(run(main))
    assert [i["title"] for i in ideas] == [f"{PREFIX} Alte Idee"], \
        "frische Ideen und Todos dürfen nicht auflaufen"
    assert ideas[0]["age_days"] == 120
    assert ideas[0]["content"] == "Salzkammergut"


def test_cooldown_silences_a_nudged_idea():
    async def main(pool):
        await _seed_ideas(pool)
        first = _mine(await _dormant_ideas(pool, 30, 90, 10))
        await _mark_nudged(pool, first[0]["id"])
        return (_mine(await _dormant_ideas(pool, 30, 90, 10)),
                _mine(await _dormant_ideas(pool, 30, 0, 10)))

    within_cooldown, after_cooldown = run(main)
    assert within_cooldown == []
    assert len(after_cooldown) == 1


def test_nudging_does_not_make_an_idea_look_recently_edited():
    """Regression zu migrations/007: der Marker darf updated_at nicht auffrischen."""
    async def main(pool):
        await _seed_ideas(pool)
        idea = _mine(await _dormant_ideas(pool, 30, 90, 10))[0]
        await _mark_nudged(pool, idea["id"])
        return _mine(await _dormant_ideas(pool, 30, 0, 10))[0]

    assert run(main)["age_days"] == 120, \
        "nudged_at hat updated_at aufgefrischt — migrations/007 fehlt in dieser Datenbank"
