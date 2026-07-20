"""Hybrid search over items: vector similarity + German full-text, fused with RRF."""
import logging

from app.ingest.embed import embed_text, to_vector_literal

logger = logging.getLogger(__name__)

RRF_K = 60


def rrf(result_lists: list[list], k: int = RRF_K, limit: int | None = None) -> list:
    """Reciprocal Rank Fusion. Merges several ranked id-lists into one ranking."""
    scores: dict = {}
    for lst in result_lists:
        for rank, item_id in enumerate(lst):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank + 1)
    ordered = sorted(scores, key=lambda i: scores[i], reverse=True)
    return ordered[:limit] if limit else ordered


async def hybrid_search(pool, settings, query: str, types: list[str] | None = None,
                        limit: int = 8) -> list[dict]:
    emb_lit = to_vector_literal(await embed_text(query, settings.embedding_model))
    fetch = limit * 2

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            # 1) semantic (cosine distance)
            await cur.execute(
                """
                SELECT id FROM items
                WHERE (%(types)s::text[] IS NULL OR type = ANY(%(types)s::text[]))
                ORDER BY embedding <=> %(emb)s::vector
                LIMIT %(n)s
                """,
                {"types": types, "emb": emb_lit, "n": fetch},
            )
            vec_ids = [r[0] for r in await cur.fetchall()]

            # 2) full-text (German)
            await cur.execute(
                """
                SELECT id FROM items
                WHERE fts @@ websearch_to_tsquery('german', %(q)s)
                  AND (%(types)s::text[] IS NULL OR type = ANY(%(types)s::text[]))
                ORDER BY ts_rank(fts, websearch_to_tsquery('german', %(q)s)) DESC
                LIMIT %(n)s
                """,
                {"q": query, "types": types, "n": fetch},
            )
            fts_ids = [r[0] for r in await cur.fetchall()]

    top_ids = rrf([vec_ids, fts_ids], limit=limit)
    if not top_ids:
        return []

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT i.id, i.type, i.title, i.content, i.status, i.priority,
                       i.due_at, i.tags, p.name
                FROM items i LEFT JOIN projects p ON p.id = i.project_id
                WHERE i.id = ANY(%s)
                """,
                (top_ids,),
            )
            rows = {r[0]: r for r in await cur.fetchall()}

    results = []
    for iid in top_ids:  # preserve RRF order
        r = rows.get(iid)
        if not r:
            continue
        results.append({
            "id": r[0], "type": r[1], "title": r[2], "content": r[3],
            "status": r[4], "priority": r[5],
            "due_at": r[6].isoformat() if r[6] else None,
            "tags": list(r[7] or []), "project": r[8],
        })
    return results
