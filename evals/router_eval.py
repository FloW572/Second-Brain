"""Router eval: does classify() label capture vs query correctly? (Haiku, hits the API.)"""
from app.bot.router import classify
from evals.harness import header, load_dataset, make_client, metric_line
from evals.metrics import accuracy


async def run(settings) -> float:
    header("Router — capture vs. query")
    data = load_dataset("router")
    client = make_client(settings)

    pairs = []
    wrong = []
    for case in data:
        intent = await classify(client, case["text"], settings)
        pairs.append((intent, case["expected"]))
        if intent != case["expected"]:
            wrong.append(f"    got {intent!r}, want {case['expected']!r}: {case['text']}")

    acc = accuracy(pairs)
    metric_line("accuracy", acc, f"({sum(1 for p, e in pairs if p == e)}/{len(pairs)})")
    if wrong:
        print("  Fehlklassifikationen:")
        print("\n".join(wrong))
    return acc
