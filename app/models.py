"""Lightweight type hints for records passed around the app.

These are documentation-only TypedDicts; rows are handled as plain dicts/tuples.
"""
from typing import TypedDict


class CaptureData(TypedDict, total=False):
    type: str          # todo | idea | note | reference
    title: str
    content: str | None
    project_hint: str | None
    status: str | None
    priority: int | None
    due_date: str | None   # ISO date
    tags: list[str]


ITEM_TYPES = ("todo", "idea", "note", "reference")
