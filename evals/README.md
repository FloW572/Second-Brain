# Evals — Qualitäts-Messung der modellabhängigen Schritte

Diese Evals messen die **Qualität** der KI-getriebenen Teile des Second Brain auf kleinen,
gelabelten Datensätzen und geben eine Scorecard aus. Anders als die Unit-Tests (`tests/`,
deterministische Logik, laufen unter `pytest`) rufen sie das echte Modell auf und dürfen
etwas Rauschen haben — sie sind zum **Beobachten einer Kennzahl über die Zeit** gedacht, z.B.
um zu sehen, ob eine Prompt-Änderung die Router-Trefferquote verschlechtert.

## Ausführen

Am besten **im App-Container** (dort sind DB, Embedding-Modell und der API-Key vorhanden):

```bash
docker compose exec app python -m evals.run all
# oder einzeln:
docker compose exec app python -m evals.run router
docker compose exec app python -m evals.run extract
docker compose exec app python -m evals.run retrieval
docker compose exec app python -m evals.run answer
```

## Die vier Evals

| Eval | Was gemessen wird | Kennzahl | Kosten |
|---|---|---|---|
| `router` | `classify()` — capture vs. query | Accuracy | Haiku (billig) |
| `extract` | `extract_structure()` — Typ / Fälligkeit / Priorität / Projekt | Accuracy je Feld | Haiku (billig) |
| `retrieval` | `hybrid_search()` auf einem geseedeten Korpus | hit@3, recall@5, MRR | **keine** (lokales Embedding) |
| `answer` | End-to-End-Antwort des Query-Agenten, bewertet von einem Richter-Modell | Bestanden-Quote | Opus (Agent **+** Richter) |

Die reinen Metrik-Funktionen liegen in [`metrics.py`](metrics.py) und sind unter
`tests/test_eval_metrics.py` unit-getestet.

## Datensätze

Klein und von Hand gepflegt unter [`datasets/`](datasets/). Zum Erweitern einfach Einträge
hinzufügen — je mehr Beispiele, desto aussagekräftiger die Kennzahl.

## Wichtiger Hinweis (retrieval & answer)

`retrieval` und `answer` seeden bekannte Einträge in die **echte** `items`-Tabelle
(markiert `source='eval'`) und löschen sie danach wieder. `hybrid_search` bzw. der Agent
sehen dabei **alle** Einträge — bei einer gut gefüllten Datenbank können echte Einträge die
geseedeten aus den Top-k verdrängen und die Zahlen drücken. Für saubere Werte gegen eine
kleine/leere Datenbank laufen lassen.
