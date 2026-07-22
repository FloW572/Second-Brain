"""Tests for Anthropic cost estimation and the in-process usage tracker."""
import logging

from app.usage import UsageTracker, estimate_cost


class FakeUsage:
    """Stand-in for anthropic's usage object (only the fields estimate_cost reads)."""

    def __init__(self, input_tokens=0, output_tokens=0,
                 cache_creation_input_tokens=0, cache_read_input_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens
        self.server_tool_use = None


# --- estimate_cost ---------------------------------------------------------

def test_cost_opus_input_and_output():
    # Opus 4.8: $5 in / $25 out per 1M tokens.
    cost = estimate_cost("claude-opus-4-8", FakeUsage(input_tokens=1000, output_tokens=500))
    assert cost == (1000 * 5 + 500 * 25) / 1_000_000  # 0.0175


def test_cost_matches_model_by_prefix():
    # The configured id carries a date suffix; pricing must still match.
    cost = estimate_cost("claude-haiku-4-5-20251001",
                         FakeUsage(input_tokens=1000, output_tokens=1000))
    assert cost == (1000 * 1 + 1000 * 5) / 1_000_000  # 0.006


def test_cost_applies_cache_multipliers():
    # cache write = 1.25x input, cache read = 0.10x input.
    cost = estimate_cost("claude-opus-4-8",
                         FakeUsage(cache_creation_input_tokens=1000, cache_read_input_tokens=1000))
    assert cost == (1000 * 5 * 1.25 + 1000 * 5 * 0.10) / 1_000_000  # 0.00675


def test_cost_unknown_model_is_none():
    assert estimate_cost("some-other-model", FakeUsage(input_tokens=1000)) is None


def test_cost_none_usage_is_none():
    assert estimate_cost("claude-opus-4-8", None) is None


# --- UsageTracker ----------------------------------------------------------

def test_tracker_accumulates_calls_and_cost():
    t = UsageTracker()
    t.configure("UTC")
    t.record(0.0175)
    t.record(0.006)
    assert t.total_calls == 2
    assert round(t.total_cost, 6) == round(0.0175 + 0.006, 6)


def test_tracker_warns_once_when_threshold_crossed(caplog):
    t = UsageTracker()
    t.configure("UTC", warn_threshold_usd=0.01)
    with caplog.at_level(logging.WARNING):
        t.record(0.02)   # crosses 0.01
        t.record(0.02)   # already warned
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_tracker_counts_errors_and_rate_limits():
    t = UsageTracker()
    t.configure("UTC")
    t.record_error()
    t.record_error(rate_limit=True)
    assert t.errors == 2
    assert t.rate_limits == 1
