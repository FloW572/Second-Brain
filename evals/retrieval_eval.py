"""Retrieval/RAG eval: seed a known corpus, run hybrid_search, measure hit@k / MRR / recall@k.

Fully local — uses the on-disk embedding model, no Anthropic API. Needs the database, so
run inside the app container. NOTE: hybrid_search sees ALL items, so for the cleanest
numbers run against a small or empty database; other rows can crowd the top-k.
"""
from app.db import close_pool, init_pool
from app.search import hybrid_search
from evals.harness import delete_items, header, load_dataset, seed_items
from evals.metrics import hit_at_k, mean, mrr, recall_at_k

_K = 3
_LIMIT = 5


async def run(settings) -> float:
    header(f"Retrieval — hybrid_search (hit@{_K}, MRR, recall@{_LIMIT})")
    data = load_dataset("retrieval")
    pool = await init_pool(settings.database_url)
    key_to_id: dict[str, int] = {}
    try:
        key_to_id = await seed_items(pool, settings, data["corpus"])
        id_to_key = {v: k for k, v in key_to_id.items()}

        rankings = []      # (ranked_keys, relevant_keys) for our seeded rows
        for q in data["queries"]:
            results = await hybrid_search(pool, settings, q["query"], None, _LIMIT)
            ranked = [id_to_key[r["id"]] for r in results if r["id"] in id_to_key]
            relevant = set(q["relevant"])
            rankings.append((ranked, relevant))
            top = ranked[0] if ranked else "—"
            ok = "✓" if hit_at_k(ranked, relevant, _K) else "✗"
            print(f"  {ok} top={top:<16} want={sorted(relevant)}  «{q['query']}»")

        h = mean([hit_at_k(r, rel, _K) for r, rel in rankings])
        rr = mean([recall_at_k(r, rel, _LIMIT) for r, rel in rankings])
        m = mrr(rankings)
        print()
        print(f"  hit@{_K}:      {h:6.1%}")
        print(f"  recall@{_LIMIT}:   {rr:6.1%}")
        print(f"  MRR:        {m:6.3f}")
        return h
    finally:
        await delete_items(pool, key_to_id.values())
        await close_pool()
