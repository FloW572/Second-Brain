"""Shared helpers for the eval runners: dataset loading, client, DB seeding, printing."""
import json
from pathlib import Path

from anthropic import AsyncAnthropic

from app.duetime import parse_due
from app.ingest.embed import embed_text, to_vector_literal

_DATASETS = Path(__file__).parent / "datasets"


def load_dataset(name: str):
    """Load evals/datasets/<name>.json."""
    return json.loads((_DATASETS / f"{name}.json").read_text(encoding="utf-8"))


def make_client(settings) -> AsyncAnthropic:
    return AsyncAnthropic(api_key=settings.anthropic_api_key)


async def seed_items(pool, settings, items: list[dict]) -> dict[str, int]:
    """Insert eval items (with real embeddings) and return {key: inserted id}.

    Rows are marked source='eval' and must be removed with delete_items() afterwards.
    """
    key_to_id: dict[str, int] = {}
    async with pool.connection() as conn:
        for it in items:
            text = f"{it['title']}\n{it.get('content') or ''}"
            emb = to_vector_literal(await embed_text(text, settings.embedding_model))
            due = parse_due(it["due_at"], settings.timezone) if it.get("due_at") else None
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO items (type, title, content, status, priority, due_at, "
                    "source, embedding) VALUES (%s, %s, %s, %s, %s, %s, 'eval', %s::vector) "
                    "RETURNING id",
                    (it["type"], it["title"], it.get("content"), it.get("status"),
                     it.get("priority"), due, emb),
                )
                row = await cur.fetchone()
            key_to_id[it["key"]] = row[0]
        await conn.commit()
    return key_to_id


async def delete_items(pool, ids) -> None:
    ids = list(ids)
    if not ids:
        return
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("DELETE FROM items WHERE id = ANY(%s)", (ids,))
        await conn.commit()


def header(title: str) -> None:
    print(f"\n=== {title} ===")


def metric_line(name: str, value: float, extra: str = "") -> None:
    print(f"  {name:<28} {value:6.1%}   {extra}".rstrip())
