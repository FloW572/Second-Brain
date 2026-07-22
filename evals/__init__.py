"""Offline evaluation harness for the model-dependent parts of the second brain.

Unlike the unit tests (deterministic logic, run under pytest), these evals measure the
*quality* of model-driven behaviour on small labelled datasets and print a scorecard:

    python -m evals.run router        # capture/query classification accuracy (Haiku)
    python -m evals.run extract       # structured-field extraction accuracy (Haiku)
    python -m evals.run retrieval      # hybrid_search hit@k / MRR (local embeddings, no API)
    python -m evals.run answer        # end-to-end answer quality via LLM-as-judge (Opus)
    python -m evals.run all

They hit the live Anthropic API (except `retrieval`, which is fully local) and the
`retrieval`/`answer` evals need the database, so run them inside the app container:

    docker compose exec app python -m evals.run all

The pure metric functions live in `evals.metrics` and ARE unit-tested.
"""
