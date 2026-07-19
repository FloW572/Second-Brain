"""Pure scoring functions for the eval harness — no I/O, unit-tested.

`accuracy` for classification (router), `hit_at_k` / `recall_at_k` / `mrr` for ranked
retrieval. Retrieval metrics take the ranked list of predicted ids and the set of
relevant ids for one query, and are averaged over the query set by the caller.
"""


def accuracy(pairs: list[tuple]) -> float:
    """Share of (predicted, expected) pairs that match. 0.0 for an empty set."""
    if not pairs:
        return 0.0
    correct = sum(1 for predicted, expected in pairs if predicted == expected)
    return correct / len(pairs)


def hit_at_k(ranked_ids: list, relevant_ids: set, k: int) -> float:
    """1.0 if any relevant id appears in the top-k, else 0.0 (per query)."""
    return 1.0 if set(ranked_ids[:k]) & set(relevant_ids) else 0.0


def recall_at_k(ranked_ids: list, relevant_ids: set, k: int) -> float:
    """Fraction of the relevant ids that appear in the top-k (per query)."""
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    found = set(ranked_ids[:k]) & relevant
    return len(found) / len(relevant)


def reciprocal_rank(ranked_ids: list, relevant_ids: set) -> float:
    """1/rank of the first relevant id (rank is 1-based); 0.0 if none present."""
    relevant = set(relevant_ids)
    for i, item in enumerate(ranked_ids, start=1):
        if item in relevant:
            return 1.0 / i
    return 0.0


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def mrr(rankings: list[tuple[list, set]]) -> float:
    """Mean reciprocal rank over (ranked_ids, relevant_ids) pairs."""
    return mean([reciprocal_rank(r, rel) for r, rel in rankings])
