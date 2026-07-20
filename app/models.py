"""Shared types and constants used across the app.

``CaptureData`` is the contract for the dict that flows through the capture
pipeline (extract -> normalize -> store). ``ITEM_TYPES`` is the single source
of truth for the valid item types. DB query rows are still handled as tuples.
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
