"""Pure normalization of the raw structure Claude extracts from a message.

Kept free of heavy dependencies so it is trivially unit-testable
(``app.models`` only pulls in ``typing``).
"""
from app.models import ITEM_TYPES, CaptureData, Occasion

VALID_TYPES = set(ITEM_TYPES)
VALID_KINDS = {"birthday", "anniversary", "custom"}


def normalize_occasion(raw) -> Occasion | None:
    """Keep an extracted recurring date only if it carries a usable day/month."""
    if not isinstance(raw, dict):
        return None
    try:
        month = int(raw.get("month"))
        day = int(raw.get("day"))
    except (TypeError, ValueError):
        return None
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None

    person = (raw.get("person") or "").strip() or None
    label = (raw.get("label") or "").strip() or (f"{person} Geburtstag" if person else None)
    if not label:
        return None
    kind = str(raw.get("kind") or "birthday").lower()
    if kind not in VALID_KINDS:
        kind = "custom"
    return {"label": label[:200], "person": person, "kind": kind, "month": month, "day": day}


def normalize_capture(data: CaptureData, raw_text: str) -> CaptureData:
    raw_text = (raw_text or "").strip()

    itype = str(data.get("type") or "note").lower()
    if itype not in VALID_TYPES:
        itype = "note"

    title = (data.get("title") or "").strip() or raw_text[:80] or "(ohne Titel)"
    title = title[:200]

    content = (data.get("content") or "").strip() or None
    if content is None and raw_text and raw_text != title:
        content = raw_text

    priority = data.get("priority")
    if priority not in (1, 2, 3):
        priority = None

    raw_tags = data.get("tags") or []
    tags = [t.strip() for t in raw_tags if isinstance(t, str) and t.strip()]

    status = "open" if itype == "todo" else None

    project_hint = (data.get("project_hint") or "").strip() or None
    due_at = (data.get("due_at") or "").strip() or None

    return {
        "type": itype,
        "title": title,
        "content": content,
        "priority": priority,
        "tags": tags,
        "status": status,
        "project_hint": project_hint,
        "due_at": due_at,
        "occasion": normalize_occasion(data.get("occasion")),
    }
