from datetime import datetime, timedelta, timezone

from app.memory import ConversationMemory


def test_empty_history_for_unknown_chat():
    mem = ConversationMemory()
    assert mem.get(1) == []


def test_add_and_get_roundtrip():
    mem = ConversationMemory()
    mem.add(1, "Frage", "Antwort")
    hist = mem.get(1)
    assert hist == [
        {"role": "user", "content": "Frage"},
        {"role": "assistant", "content": "Antwort"},
    ]


def test_is_capped_to_last_n():
    mem = ConversationMemory(max_messages=4)  # last 2 exchanges
    for i in range(5):
        mem.add(1, f"q{i}", f"a{i}")
    hist = mem.get(1)
    assert len(hist) == 4
    assert hist[0] == {"role": "user", "content": "q3"}   # oldest kept
    assert hist[-1] == {"role": "assistant", "content": "a4"}


def test_chats_are_independent():
    mem = ConversationMemory()
    mem.add(1, "q1", "a1")
    mem.add(2, "q2", "a2")
    assert mem.get(1)[0]["content"] == "q1"
    assert mem.get(2)[0]["content"] == "q2"


def test_clear_forgets_chat():
    mem = ConversationMemory()
    mem.add(1, "q", "a")
    mem.clear(1)
    assert mem.get(1) == []


def test_idle_reset_forgets_stale_context():
    clock = {"t": datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)}
    mem = ConversationMemory(idle_reset_minutes=30, now_fn=lambda: clock["t"])
    mem.add(1, "q", "a")
    clock["t"] += timedelta(minutes=31)   # more silence than the idle window
    assert mem.get(1) == []
