from app.ingest.normalize import normalize_capture


def test_defaults_to_note():
    out = normalize_capture({}, "irgendein loser Gedanke")
    assert out["type"] == "note"
    assert out["title"] == "irgendein loser Gedanke"
    assert out["status"] is None


def test_todo_gets_open_status():
    out = normalize_capture({"type": "todo", "title": "Rechnung zahlen"}, "Rechnung zahlen")
    assert out["status"] == "open"


def test_invalid_type_falls_back_to_note():
    out = normalize_capture({"type": "banana", "title": "X"}, "X")
    assert out["type"] == "note"


def test_invalid_priority_is_dropped():
    out = normalize_capture({"type": "todo", "title": "X", "priority": 9}, "X")
    assert out["priority"] is None


def test_tags_are_stripped_and_filtered():
    out = normalize_capture({"type": "idea", "title": "Y", "tags": ["a", " ", "b "]}, "Y")
    assert out["tags"] == ["a", "b"]


def test_content_falls_back_to_raw_when_longer_than_title():
    out = normalize_capture({"type": "note", "title": "Kurz"}, "Ein deutlich längerer Rohtext")
    assert out["content"] == "Ein deutlich längerer Rohtext"


def test_empty_project_hint_becomes_none():
    out = normalize_capture({"type": "note", "title": "X", "project_hint": "  "}, "X")
    assert out["project_hint"] is None
