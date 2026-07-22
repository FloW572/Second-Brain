"""Tests for the pure eval scoring functions."""
from evals.metrics import (
    accuracy,
    hit_at_k,
    mrr,
    reciprocal_rank,
    recall_at_k,
)


def test_accuracy_basic():
    assert accuracy([("a", "a"), ("b", "b"), ("a", "b")]) == 2 / 3


def test_accuracy_empty():
    assert accuracy([]) == 0.0


def test_hit_at_k_present_and_absent():
    assert hit_at_k([3, 1, 2], {1}, k=3) == 1.0
    assert hit_at_k([3, 1, 2], {1}, k=1) == 0.0   # 1 is not in top-1
    assert hit_at_k([3, 1, 2], {9}, k=3) == 0.0


def test_recall_at_k():
    # two relevant, one in top-2
    assert recall_at_k([5, 1, 2, 4], {1, 9}, k=2) == 0.5
    assert recall_at_k([1, 9, 3], {1, 9}, k=3) == 1.0
    assert recall_at_k([1, 2], set(), k=2) == 0.0


def test_reciprocal_rank():
    assert reciprocal_rank([3, 1, 2], {1}) == 0.5        # first relevant at rank 2
    assert reciprocal_rank([1, 2, 3], {1}) == 1.0
    assert reciprocal_rank([3, 2], {1}) == 0.0


def test_mrr_averages_reciprocal_ranks():
    rankings = [([3, 1], {1}), ([1, 2], {1})]            # 0.5 and 1.0
    assert mrr(rankings) == 0.75
