"""Short-term, per-chat conversation memory so follow-up questions keep context.

Kept in-memory (a dict in the bot process): a conversation is short-lived, so
losing it on restart is acceptable and avoids a schema change. Only the query
agent uses it. Bounded to the last few turns and forgotten after inactivity.
"""
from datetime import datetime, timedelta, timezone

MAX_MESSAGES = 6          # keep the last 3 exchanges (user + assistant each)
IDLE_RESET_MINUTES = 30   # forget the context after this much silence


class ConversationMemory:
    def __init__(self, max_messages: int = MAX_MESSAGES,
                 idle_reset_minutes: int = IDLE_RESET_MINUTES, now_fn=None):
        self._chats: dict = {}                      # chat_id -> {"messages": [...], "last": dt}
        self._max = max_messages
        self._idle = timedelta(minutes=idle_reset_minutes)
        self._now = now_fn or (lambda: datetime.now(timezone.utc))

    def _fresh(self, chat_id):
        """Return the chat entry, or None if missing or gone stale (dropping stale)."""
        entry = self._chats.get(chat_id)
        if entry is None:
            return None
        if self._now() - entry["last"] > self._idle:
            self._chats.pop(chat_id, None)
            return None
        return entry

    def get(self, chat_id) -> list:
        """Recent messages (role/content dicts) for the Anthropic API, oldest first."""
        entry = self._fresh(chat_id)
        return list(entry["messages"]) if entry else []

    def add(self, chat_id, question: str, answer: str) -> None:
        """Record one query turn (user question + assistant answer)."""
        entry = self._fresh(chat_id)
        if entry is None:
            entry = {"messages": [], "last": self._now()}
            self._chats[chat_id] = entry
        entry["messages"].append({"role": "user", "content": question})
        entry["messages"].append({"role": "assistant", "content": answer})
        entry["messages"] = entry["messages"][-self._max:]   # keep only the last N
        entry["last"] = self._now()

    def clear(self, chat_id) -> None:
        self._chats.pop(chat_id, None)
