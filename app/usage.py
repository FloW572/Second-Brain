"""Anthropic usage & cost observability.

`create_message` is a thin wrapper around `anthropic.messages.create` that times the
call, logs a structured line (tokens, latency, estimated USD cost), counts failures /
rate-limits, and persists one row per call to the `usage_log` table. `/stats` reads
that table for today's and this month's totals (surviving restarts); the in-memory
tracker keeps process-scoped operational counters (errors, rate-limits) and drives the
optional spend-warning.

Prices are USD per 1M tokens and MUST be kept in sync with the models configured in
`app/config.py` (ROUTER_MODEL / EXTRACT_MODEL / QUERY_MODEL). The dollar figure is an
ESTIMATE: token counts are Anthropic's own, but the rates are a local snapshot and
server-tool (web-search) costs are not included.
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# USD per 1M tokens (input, output). Cache writes bill ~1.25x input, reads ~0.1x input.
_PRICING = {
    "claude-opus-4-8": {"input": 5.00, "output": 25.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}
_CACHE_WRITE_MULT = 1.25
_CACHE_READ_MULT = 0.10
_PER_MILLION = 1_000_000

# Friendly, role-oriented label per model prefix, for the /stats breakdown.
_ROLE = {
    "claude-opus-4-8": "Opus (Reasoning/Recherche)",
    "claude-haiku-4-5": "Haiku (Routing/Extraktion)",
}


def _match(model: str, table: dict):
    """Model ids may carry a date suffix (claude-haiku-4-5-20251001) — match by prefix."""
    for key, value in table.items():
        if model.startswith(key):
            return value
    return None


def _u(usage, name: str) -> int:
    return getattr(usage, name, 0) or 0


def estimate_cost(model: str, usage) -> float | None:
    """USD cost of one call, or None if the model isn't in the price table."""
    rates = _match(model, _PRICING)
    if rates is None or usage is None:
        return None
    cost = (
        _u(usage, "input_tokens") * rates["input"]
        + _u(usage, "cache_creation_input_tokens") * rates["input"] * _CACHE_WRITE_MULT
        + _u(usage, "cache_read_input_tokens") * rates["input"] * _CACHE_READ_MULT
        + _u(usage, "output_tokens") * rates["output"]
    )
    return cost / _PER_MILLION


def _web_search_count(usage) -> int:
    server = getattr(usage, "server_tool_use", None)
    return getattr(server, "web_search_requests", 0) or 0 if server else 0


def _is_rate_limit(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) == 429 or "RateLimit" in type(exc).__name__


@dataclass
class UsageTracker:
    """Process-wide counters since (re)start: drives the spend-warning and /stats ops line."""

    started_at: datetime | None = None
    warn_threshold_usd: float = 0.0
    total_calls: int = 0
    total_cost: float = 0.0
    errors: int = 0
    rate_limits: int = 0
    _warned: bool = False

    def configure(self, timezone: str, warn_threshold_usd: float = 0.0) -> None:
        self.started_at = datetime.now(ZoneInfo(timezone))
        self.warn_threshold_usd = warn_threshold_usd or 0.0

    def record(self, cost: float | None) -> None:
        self.total_calls += 1
        self.total_cost += cost or 0.0
        if self.warn_threshold_usd and not self._warned and self.total_cost >= self.warn_threshold_usd:
            self._warned = True
            logger.warning(
                "Anthropic-Ausgaben seit Start haben %.2f USD überschritten (aktuell ~%.2f USD).",
                self.warn_threshold_usd, self.total_cost,
            )

    def record_error(self, rate_limit: bool = False) -> None:
        self.errors += 1
        if rate_limit:
            self.rate_limits += 1


# Process-wide singleton — the bot runs as one process. Configured once from settings
# in app.main._post_init, which also hands us the DB pool via set_pool().
tracker = UsageTracker()
_pool = None


def set_pool(pool) -> None:
    """Give the usage layer a DB pool so calls can be persisted to usage_log."""
    global _pool
    _pool = pool


async def _persist(label: str, model: str, usage, web: int, cost: float | None) -> None:
    """Append one row to usage_log. Guarded: a DB hiccup must never break a user reply."""
    if _pool is None or usage is None:
        return
    try:
        async with _pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO usage_log (label, model, input_tokens, cache_creation_tokens, "
                "cache_read_tokens, output_tokens, web_searches, cost_usd) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (label, model, _u(usage, "input_tokens"), _u(usage, "cache_creation_input_tokens"),
                 _u(usage, "cache_read_input_tokens"), _u(usage, "output_tokens"), web, cost or 0.0),
            )
            await conn.commit()
    except Exception:  # noqa: BLE001 - persistence is best-effort observability
        logger.debug("usage_log persist failed", exc_info=True)


async def usage_report(pool, timezone: str) -> list[str]:
    """Plain-text /stats lines: today + this-month totals from usage_log (no Markdown)."""
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT count(*), coalesce(sum(cost_usd), 0) FROM usage_log WHERE created_at >= %s",
            (start_today,),
        )
        today_calls, today_cost = await cur.fetchone()
        await cur.execute(
            "SELECT count(*), coalesce(sum(cost_usd), 0), coalesce(sum(web_searches), 0) "
            "FROM usage_log WHERE created_at >= %s",
            (start_month,),
        )
        month_calls, month_cost, month_web = await cur.fetchone()
        await cur.execute(
            "SELECT model, count(*), coalesce(sum(cost_usd), 0) FROM usage_log "
            "WHERE created_at >= %s GROUP BY model ORDER BY model",
            (start_month,),
        )
        per_model = await cur.fetchall()

    lines = ["📊 Anthropic-Nutzung (geschätzt)",
             f"Heute: {today_calls} Anfragen · ~${float(today_cost):.2f}",
             f"Diesen Monat: {month_calls} Anfragen · ~${float(month_cost):.2f}"]
    if month_web:
        lines.append(f"🔎 Websuchen (Monat): {int(month_web)} (Suchkosten nicht eingerechnet)")
    if per_model:
        lines.append("\nDiesen Monat je Modell:")
        for model, calls, cost in per_model:
            role = _match(model, _ROLE) or model
            lines.append(f"  {role}: {calls} · ~${float(cost):.2f}")
    ops = f"\nSeit Start (Prozess): {tracker.total_calls} Anfragen, {tracker.errors} Fehler"
    if tracker.rate_limits:
        ops += f", {tracker.rate_limits} Rate-Limits"
    lines.append(ops)
    if tracker.warn_threshold_usd:
        lines.append(f"⚠️ Warnschwelle (Prozess-Summe): ${tracker.warn_threshold_usd:.2f}")
    return lines


async def create_message(anthropic, *, label: str, **kwargs):
    """Call anthropic.messages.create, logging tokens/latency/cost, counting failures,
    and persisting the call to usage_log.

    `label` names the call site (router/extract/query/research). Other kwargs are
    forwarded verbatim to messages.create. Exceptions are counted and re-raised so the
    existing call-site error handling is unchanged.
    """
    model = kwargs.get("model", "?")
    started = time.monotonic()
    try:
        resp = await anthropic.messages.create(**kwargs)
    except Exception as exc:
        rate_limited = _is_rate_limit(exc)
        tracker.record_error(rate_limit=rate_limited)
        logger.warning(
            "anthropic label=%s model=%s FEHLGESCHLAGEN nach %.2fs: %s%s",
            label, model, time.monotonic() - started, type(exc).__name__,
            " (rate-limit)" if rate_limited else "",
        )
        raise

    latency = time.monotonic() - started
    usage = getattr(resp, "usage", None)
    cost = estimate_cost(model, usage)
    web = _web_search_count(usage)
    if usage is not None:
        tracker.record(cost)

    logger.info(
        "anthropic label=%s model=%s in=%s cache_w=%s cache_r=%s out=%s web=%s latency=%.2fs cost=%s",
        label, model,
        _u(usage, "input_tokens"), _u(usage, "cache_creation_input_tokens"),
        _u(usage, "cache_read_input_tokens"), _u(usage, "output_tokens"),
        web, latency, f"${cost:.4f}" if cost is not None else "n/a",
    )
    await _persist(label, model, usage, web, cost)
    return resp
