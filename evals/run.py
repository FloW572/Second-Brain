"""Eval runner CLI.

    python -m evals.run [router|extract|retrieval|answer|all]

Run inside the app container so the DB and embedding model are available:

    docker compose exec app python -m evals.run all
"""
import asyncio
import sys

from app.config import get_settings
from evals import answer_eval, extract_eval, retrieval_eval, router_eval

_EVALS = {
    "router": router_eval.run,
    "extract": extract_eval.run,
    "retrieval": retrieval_eval.run,
    "answer": answer_eval.run,
}


async def _main(names: list[str]) -> None:
    settings = get_settings()
    results = {}
    for name in names:
        results[name] = await _EVALS[name](settings)
    print("\n=== Zusammenfassung ===")
    for name, score in results.items():
        print(f"  {name:<10} {score:6.1%}")


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    if arg == "all":
        names = list(_EVALS)
    elif arg in _EVALS:
        names = [arg]
    else:
        print(f"Unbekannt: {arg!r}. Optionen: {', '.join(_EVALS)}, all")
        raise SystemExit(2)
    asyncio.run(_main(names))


if __name__ == "__main__":
    main()
