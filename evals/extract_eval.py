"""Extraction eval: does extract_structure() get type / due / priority / project right?

Only the structured fields present in each case's `expected` are graded (the free-text
title is not). `due` is graded as a boolean: did a due date get parsed at all? (Haiku, API.)
"""
from app.ingest.extract import extract_structure
from evals.harness import header, load_dataset, make_client, metric_line
from evals.metrics import accuracy


async def run(settings) -> float:
    header("Extraktion — strukturierte Felder")
    data = load_dataset("extract")
    client = make_client(settings)

    fields: dict[str, list] = {"type": [], "due": [], "priority": [], "project": []}
    for case in data:
        got = await extract_structure(client, case["text"], settings)
        exp = case["expected"]
        fields["type"].append((got.get("type"), exp["type"]))
        if "due" in exp:
            fields["due"].append((bool(got.get("due_at")), exp["due"]))
        if "priority" in exp:
            fields["priority"].append((got.get("priority"), exp["priority"]))
        if "project" in exp:
            hint = (got.get("project_hint") or "").lower()
            fields["project"].append((exp["project"].lower() in hint, True))

    scores = {name: accuracy(pairs) for name, pairs in fields.items() if pairs}
    for name, score in scores.items():
        metric_line(name, score, f"(n={len(fields[name])})")
    overall = sum(scores.values()) / len(scores) if scores else 0.0
    metric_line("Ø über Felder", overall)
    return overall
