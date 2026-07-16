from app.search import rrf


def test_rrf_ranks_item_in_both_lists_first():
    vector_hits = [1, 2, 3]
    fts_hits = [1, 4, 5]
    order = rrf([vector_hits, fts_hits])
    assert order[0] == 1  # only id present (and top) in both lists


def test_rrf_returns_union_of_ids():
    order = rrf([[1, 2], [2, 3]])
    assert set(order) == {1, 2, 3}


def test_rrf_respects_limit():
    order = rrf([[1, 2, 3, 4], [5, 6]], limit=2)
    assert len(order) == 2


def test_rrf_empty():
    assert rrf([[], []]) == []
