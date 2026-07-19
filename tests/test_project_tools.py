"""Tests for the project-management tools (`rename_project`, `delete_project`).

These handlers are DB-coupled, so we drive them against a tiny in-memory fake that
speaks just enough of the SQL they (and `resolve_project`) issue — no real Postgres
and no extra test dependency. The async handlers are run via ``asyncio.run``.
"""
import asyncio

from app.query.tools import _delete_project, _rename_project


def run(coro):
    return asyncio.run(coro)


# --- tiny fake DB -----------------------------------------------------------

class FakeDB:
    """In-memory stand-in interpreting the handful of queries the handlers issue."""

    def __init__(self, projects=None, items=None, documents=None):
        self.projects = projects or []          # dicts: id, name, status
        self.items = items or []                # dicts: project_id
        self.documents = documents or []        # dicts: project_id

    def _active(self):
        return [p for p in sorted(self.projects, key=lambda x: x["id"])
                if p["status"] != "archived"]

    def run(self, sql, params):
        q = " ".join(sql.lower().split())
        params = tuple(params or ())

        if q.startswith("update projects set name"):
            new_name, pid = params
            for p in self.projects:
                if p["id"] == pid:
                    p["name"] = new_name
                    return (p["id"], p["name"])
            return None

        if q.startswith("delete from projects where id"):
            (pid,) = params
            victim = next((p for p in self.projects if p["id"] == pid), None)
            if victim:
                self.projects.remove(victim)
                return (victim["name"],)
            return None

        if "count(*) from items" in q:
            (pid,) = params
            return (sum(1 for i in self.items if i["project_id"] == pid),)

        if "count(*) from documents" in q:
            (pid,) = params
            return (sum(1 for d in self.documents if d["project_id"] == pid),)

        # rename's clash check: SELECT id ... AND id <> %s
        if q.startswith("select id from projects") and "id <>" in q:
            new_name, pid = params
            for p in self._active():
                if p["id"] != pid and p["name"].lower() == new_name.lower():
                    return (p["id"],)
            return None

        # dashboard's exact id lookup
        if q.startswith("select id, name from projects") and "where id =" in q:
            (pid,) = params
            for p in self._active():
                if p["id"] == pid:
                    return (p["id"], p["name"])
            return None

        # resolve_project: exact-ish (1 param) then fuzzy (2 params)
        if q.startswith("select id, name from projects"):
            if len(params) == 1:                        # name ILIKE hint (no wildcards)
                hint = params[0].lower()
                for p in self._active():
                    if p["name"].lower() == hint:
                        return (p["id"], p["name"])
                return None
            _, hint = params                            # fuzzy: ("%hint%", hint)
            needle = hint.lower()
            for p in self._active():
                name = p["name"].lower()
                if needle in name or name in needle:
                    return (p["id"], p["name"])
            return None

        raise AssertionError(f"unhandled query: {q!r}")


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self._one = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, params=None):
        self._one = self.db.run(sql, params)

    async def fetchone(self):
        return self._one


class FakeConn:
    def __init__(self, db):
        self.db = db
        self.committed = False

    def cursor(self):
        return FakeCursor(self.db)

    async def commit(self):
        self.committed = True


class FakeConnCtx:
    def __init__(self, db):
        self.conn = FakeConn(db)

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class FakePool:
    def __init__(self, db):
        self.db = db

    def connection(self):
        return FakeConnCtx(self.db)


# --- rename_project ---------------------------------------------------------

def test_rename_updates_name_and_keeps_items_attached():
    db = FakeDB(
        projects=[{"id": 7, "name": "Bier Gut", "status": "active"}],
        items=[{"project_id": 7}, {"project_id": 7}],
    )
    res = run(_rename_project(FakePool(db), None,
                              {"project": "Bier Gut", "new_name": "Bier"}))
    assert res == {"renamed": True, "id": 7, "old_name": "Bier Gut", "name": "Bier"}
    assert db.projects[0]["name"] == "Bier"
    # both notes still point at the same project — renaming never detaches them
    assert [i["project_id"] for i in db.items] == [7, 7]


def test_rename_missing_project():
    db = FakeDB(projects=[])
    res = run(_rename_project(FakePool(db), None,
                              {"project": "Ghost", "new_name": "X"}))
    assert res["renamed"] is False
    assert "no project matching" in res["reason"]


def test_rename_refuses_when_new_name_clashes_with_other_project():
    db = FakeDB(projects=[
        {"id": 1, "name": "Bier Gut", "status": "active"},
        {"id": 2, "name": "Bier", "status": "active"},
    ])
    res = run(_rename_project(FakePool(db), None,
                              {"project": "Bier Gut", "new_name": "Bier"}))
    assert res["renamed"] is False
    assert "already exists" in res["reason"]
    assert db.projects[0]["name"] == "Bier Gut"   # unchanged


def test_rename_requires_both_fields():
    db = FakeDB(projects=[{"id": 1, "name": "A", "status": "active"}])
    assert run(_rename_project(FakePool(db), None, {"project": "A"}))["renamed"] is False
    assert run(_rename_project(FakePool(db), None, {"new_name": "B"}))["renamed"] is False


def test_rename_by_id_used_by_dashboard():
    # The web dashboard renames by exact id, not by (fuzzy) name.
    db = FakeDB(projects=[
        {"id": 1, "name": "Bier", "status": "active"},
        {"id": 2, "name": "Bier Gut", "status": "active"},
    ])
    res = run(_rename_project(FakePool(db), None, {"id": 2, "new_name": "Biergarten"}))
    assert res == {"renamed": True, "id": 2, "old_name": "Bier Gut", "name": "Biergarten"}
    assert db.projects[1]["name"] == "Biergarten"
    assert db.projects[0]["name"] == "Bier"        # untouched


# --- delete_project ---------------------------------------------------------

def test_delete_removes_empty_project():
    db = FakeDB(projects=[{"id": 5, "name": "Leer", "status": "active"}])
    res = run(_delete_project(FakePool(db), None, {"project": "Leer"}))
    assert res == {"deleted": True, "id": 5, "name": "Leer"}
    assert db.projects == []


def test_delete_refuses_when_project_has_items():
    db = FakeDB(
        projects=[{"id": 7, "name": "Bier Gut", "status": "active"}],
        items=[{"project_id": 7}, {"project_id": 7}],
    )
    res = run(_delete_project(FakePool(db), None, {"project": "Bier Gut"}))
    assert res["deleted"] is False
    assert res["items"] == 2
    assert db.projects                            # still there


def test_delete_refuses_when_project_has_documents():
    db = FakeDB(
        projects=[{"id": 3, "name": "Fotos", "status": "active"}],
        documents=[{"project_id": 3}],
    )
    res = run(_delete_project(FakePool(db), None, {"project": "Fotos"}))
    assert res["deleted"] is False
    assert res["documents"] == 1


def test_delete_missing_project():
    db = FakeDB(projects=[])
    res = run(_delete_project(FakePool(db), None, {"project": "Ghost"}))
    assert res["deleted"] is False
    assert "no project matching" in res["reason"]


def test_delete_by_id_used_by_dashboard():
    # The web dashboard deletes by exact id, not by (fuzzy) name.
    db = FakeDB(projects=[
        {"id": 1, "name": "Bier", "status": "active"},
        {"id": 2, "name": "Bier Gut", "status": "active"},
    ])
    res = run(_delete_project(FakePool(db), None, {"id": 2}))
    assert res == {"deleted": True, "id": 2, "name": "Bier Gut"}
    assert [p["id"] for p in db.projects] == [1]   # only id 2 removed
