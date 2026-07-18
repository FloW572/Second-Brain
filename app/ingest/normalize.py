"""Pure normalization of the raw structure Claude extracts from a message.

Kept dependency-free so it is trivially unit-testable.
"""
VALID_TYPES = {"todo", "idea", "note", "reference"}


def normalize_capture(data: dict, raw_text: str) -> dict:
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
    due_date = (data.get("due_date") or "").strip() or None

    return {
        "type": itype,
        "title": title,
        "content": content,
        "priority": priority,
        "tags": tags,
        "status": status,
        "project_hint": project_hint,
        "due_date": due_date,
    }
