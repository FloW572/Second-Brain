"""Answer-quality eval (LLM-as-judge): seed known data, ask questions end-to-end via the
query agent, then have a judge model score each answer against a per-question rubric.

Hits the Anthropic API twice per question (agent + judge) and needs the database — run
inside the app container. The judge is a separate call with a forced verdict tool.
"""
from app.db import close_pool, init_pool
from app.query.agent import answer
from app.usage import create_message
from evals.harness import delete_items, header, load_dataset, make_client, seed_items
from evals.metrics import mean

_JUDGE_TOOL = {
    "name": "verdict",
    "description": "Bewerte, ob die Antwort die Rubrik erfüllt.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pass": {"type": "boolean", "description": "true = Rubrik erfüllt."},
            "reason": {"type": "string", "description": "Kurze Begründung."},
        },
        "required": ["pass", "reason"],
    },
}
_JUDGE_SYSTEM = (
    "Du bist ein strenger, fairer Bewerter. Gegeben eine Frage, eine Bewertungs-Rubrik und "
    "die Antwort eines Assistenten: Erfüllt die Antwort die Rubrik inhaltlich? Kleine "
    "Formulierungsunterschiede sind egal, es zählt der Inhalt. Antworte nur über das Tool."
)


async def _judge(client, settings, question: str, rubric: str, reply: str) -> dict:
    resp = await create_message(
        client,
        label="judge",
        model=settings.query_model,
        max_tokens=300,
        system=_JUDGE_SYSTEM,
        tools=[_JUDGE_TOOL],
        tool_choice={"type": "tool", "name": "verdict"},
        messages=[{"role": "user",
                   "content": f"Frage: {question}\n\nRubrik: {rubric}\n\nAntwort: {reply}"}],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "verdict":
            return dict(block.input)
    return {"pass": False, "reason": "kein Urteil erhalten"}


async def run(settings) -> float:
    header("Antwortqualität — LLM-as-judge")
    data = load_dataset("answer")
    pool = await init_pool(settings.database_url)
    client = make_client(settings)
    key_to_id: dict[str, int] = {}
    try:
        key_to_id = await seed_items(pool, settings, data["seed"])
        verdicts = []
        for q in data["questions"]:
            reply = await answer(client, pool, q["question"], settings)
            verdict = await _judge(client, settings, q["question"], q["rubric"], reply)
            verdicts.append(bool(verdict.get("pass")))
            mark = "✓" if verdict.get("pass") else "✗"
            print(f"  {mark} «{q['question']}»")
            print(f"       → {verdict.get('reason', '')}")

        acc = mean([1.0 if v else 0.0 for v in verdicts])
        print(f"\n  Bestanden: {acc:.1%} ({sum(verdicts)}/{len(verdicts)})")
        return acc
    finally:
        await delete_items(pool, key_to_id.values())
        await close_pool()
