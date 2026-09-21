# Orchestrated Loop Demo

Leichtgewichtiges, startfaehiges Beispiel fuer einen zielgetriebenen Agenten-Loop:
Ziel annehmen, planen, zerlegen, recherchieren, umsetzen, reviewen und die naechste
Iteration aus den Review-Gaps ableiten.

Die Demo nutzt lokale, deterministische APIs fuer vier Rollen:

- `Orchestrator`: liest Status und erzeugt den naechsten Plan.
- `Researcher`: beantwortet Wissensluecken mit lokalen Source-Handles.
- `Builder`: erzeugt deterministische Artefakte im Workspace.
- `Judge`: bewertet die Artefakte gegen Zielkriterien und erzeugt Next Actions.

## Schnellstart

```powershell
git clone https://github.com/dynamic-dome/orchestrated-bridge.git
cd orchestrated-bridge
python -m pip install -e ".[test]"
python -m pytest
python -m orchestrated_loop --goal "Build a productive agent system that plans, decomposes, researches, implements, reviews, and improves." --max-iter 5 --target 0.85
```

Alternativ kann das Ziel aus einer Datei kommen:

```powershell
python -m orchestrated_loop --goal-file .\goal.txt --workspace . --max-iter 5 --target 0.9
```

## Beispiel-Task

Ohne `--goal` nutzt die Demo weiter den Glossar-Prototyp als Default-Ziel, damit
alte Smoke-Tests stabil bleiben. Mit `--goal` wird der gesamte Loop auf das neue
Ziel ausgerichtet.

Die Demo schreibt je Lauf:

- `state/ADAPTERS.json`
- `state/ADAPTER_EVENTS.jsonl`
- `state/AGENT_CARDS.json`
- `state/ARTIFACTS.json`
- `state/DCO_HANDOFF.json`
- `state/DCO_IMPORT.json`
- `state/DCO_WORKER_TASKS.json`
- `state/DCO_VALIDATION.json`
- `state/DCO_AUDIT.jsonl`
- `state/GOAL.md`
- `state/GOAL.json`
- `state/PLAN.md`
- `state/TASKS.json`
- `state/RESEARCH.md`
- `state/TODO.md`
- `state/REVIEW.md`
- `state/HANDOFF.md`
- `state/LOG.md`
- `state/DECISIONS.md`
- `state/RESULTS.json`
- `state/RUN_MANIFEST.json`
- `state/RUN_STATUS.json`
- `state/RUN_STATUS.md`
- `state/FINAL_REPORT.json` (nach expliziter Akzeptanz)
- `state/FINAL_REPORT.md` (nach expliziter Akzeptanz)
- `state/TRACE.jsonl`
- `eval/round-*.json`
- `deliverables/iteration-*-goal-packet.md`

## Loop-Vertrag

1. `Goal` beschreibt Objective, Success Criteria, Constraints und erwartete Deliverables.
2. `Plan` zerlegt das Ziel in Work Items fuer `plan`, `research`, `build`, `review`, `improve`.
3. `Researcher` liefert Findings und Source-Handles.
4. `Builder` erzeugt Artefakte nur innerhalb des gewaehlten Workspaces.
5. `Judge` scored die Runde, markiert Blocker und schreibt konkrete Next Actions.
6. Die naechste Iteration uebernimmt diese Next Actions als `improvement_focus`.

## Run-Vertrag

Externe Orchestratoren lesen vor allem:

- `state/RUN_MANIFEST.json`: stabile `run_id`, Ziel, Adapter, Status, Iterationen,
  Scores, Blocker, Next Actions.
- `state/RUN_STATUS.json`: kompakte Operator-/Orchestrator-Sicht auf Ziel,
  Status, Review, Adaptergesundheit, DCO-Bereitschaft und empfohlene naechste Aktion.
- `state/ADAPTER_EVENTS.jsonl`: append-only Laufspur aller externen Adapterversuche
  mit Status, Dauer, Fehlertext und Retry-Information.
- `state/ARTIFACTS.json`: Index aller relevanten State-, Eval- und Deliverable-Dateien.
- `state/DCO_HANDOFF.json`: DCO-kompatibler Importvertrag mit Ziel, Kontext, Work
  Items, Verifikation, Safety-Grenzen und Statusentscheidung.
- `state/DCO_IMPORT.json`: read-only Importpaket fuer externe Orchestratoren.
- `state/DCO_WORKER_TASKS.json`: aus Work Items abgeleitetes Worker-Backlog mit
  Rollen, Input-/Output-Contracts, Scope-Grenzen und Verification-Checks.
- `state/AGENT_CARDS.json`: maschinenlesbare Rollenprofile fuer Planner,
  Researcher, Implementer, Verifier und Supervisor mit DCO-Profil, Capabilities,
  Tools, erlaubten Stages, Handoff-Vertrag und Safety-Regeln.
- `state/TRACE.jsonl`: append-only Ablaufspur fuer Plan, Research, Build, Review und Improve.
- `state/HANDOFF.md`: menschenlesbare Uebergabe fuer den naechsten Agenten.

Ein Resume im gleichen Workspace behaelt dieselbe `run_id` und erweitert Manifest,
Results und Trace um weitere Iterationen.

Der DCO-Handoff ist read-only fuer den echten DCO: Er schreibt nur in den gewaehlen
Workspace und mutiert keine DCO-Datenbank.

Wenn DCO einen importierten Workflow abgeschlossen hat, kann er die Worker-
Outputs als `state/DCO_WORKER_RESULTS.json` und `state/DCO_WORKER_RESULTS.md`
in denselben Workspace zurueckschreiben. Der naechste Resume-Lauf liest diese
Datei einmalig als externen Verbesserungsinput, ergaenzt die naechste Planung um
die DCO-Worker-Findings und markiert den Ingest per Hash in
`state/RESULTS.json`, damit dieselben Resultate nicht endlos erneut in den
Plan wandern.

Vor einem Import kann der Handoff validiert werden:

```powershell
python -m orchestrated_loop.dco_validate --workspace .
```

Der Validator schreibt `state/DCO_VALIDATION.json` und prueft unter anderem
`run_id`-Konsistenz, Work Items, Verification-Dateien, Status/Decision-Konsistenz
und `safety.mutates_dco = false`. Workspace-Pfade werden aufgeloest, damit ein
mit relativem Pfad gestarteter Lauf auch ueber den absoluten Workspace validierbar ist.

Ein read-only Worker-Backlog fuer den DCO-Import erzeugst du danach so:

```powershell
python -m orchestrated_loop.dco_import --workspace .
```

Der Importer validiert zuerst den Handoff, schreibt dann `state/DCO_IMPORT.json`,
`state/DCO_WORKER_TASKS.json`, `state/AGENT_CARDS.json` und
`state/DCO_AUDIT.jsonl` und ergaenzt diese Dateien im Artefaktindex. Bei harten
Validierungsfehlern wird kein Worker-Backlog geschrieben. Jeder Worker-Task
referenziert seine Rollenkarte per `agent_card_ref`.

Eine kompakte Operator-Sicht erzeugst du danach so:

```powershell
python -m orchestrated_loop.run_status --workspace .
```

Der Status-Builder schreibt `state/RUN_STATUS.json` und `state/RUN_STATUS.md`. Der
normale Orchestratorlauf befuellt diese Dateien automatisch; nach spaeterer DCO-
Validierung oder Importpaket-Erzeugung kann der Befehl erneut laufen. Er verdichtet
Manifest, Review, Adapter-Events, DCO-Validation und DCO-Import zu einer Entscheidung
wie `queue_dco_workers`, `review_adapter_events`, `run_next_iteration` oder
`inspect_blocker`.

Wenn `RUN_STATUS.operator.recommended_action` auf `accept_run` steht, kann die
Abschlussakte erzeugt werden:

```powershell
python -m orchestrated_loop.final_report --workspace .
```

Der Final-Report schreibt `state/FINAL_REPORT.json` und
`state/FINAL_REPORT.md`, referenziert Ziel, Status, Review-Score,
Artefaktindex und optional vorhandene `DCO_WORKER_RESULTS` und ergaenzt beide
Dateien im Artefaktindex. Bei nicht akzeptierten Laeufen bricht der Befehl ab,
damit eine offene Verbesserungsrunde nicht versehentlich als fertig markiert
wird.

## Adapter

Externe Rollen koennen per JSON-Konfiguration angebunden werden:

```powershell
python -m orchestrated_loop --goal "..." --adapter-config .\adapters.local.json
```

Siehe `ADAPTERS.md` fuer den Rollenvertrag. Command-Adapter bekommen JSON ueber
`stdin`, liefern JSON ueber `stdout`, laufen ohne Shell, koennen mit `max_attempts`
transiente Fehler erneut versuchen und koennen optional auf die lokale Rolle
zurueckfallen.

Ein OpenAI-Researcher-Adapter ist enthalten:

```powershell
$env:OPENAI_API_KEY = "<nicht-ins-repo-schreiben>"
$env:ORCHESTRATED_LOOP_OPENAI_MODEL = "gpt-5"
python -m orchestrated_loop --goal "..." --adapter-config .\adapters.openai.example.json
```

Ein Claude-Code-Rollenadapter fuer `builder` und `judge` ist ebenfalls enthalten:

```powershell
python -m orchestrated_loop --goal "..." --adapter-config .\adapters.claude-code.example.json
```

Der Claude-Code-Adapter ist gegen die aktuelle `claude.exe`-Ausgabe gehaertet:
er kann das echte JSON-Event-Array, BOM/trailing Hook-Noise und kurzen Prosa-Text
vor dem Rollen-JSON parsen. Am 2026-05-30 wurden `builder` und `judge` isoliert
gegen `claude.exe` ohne Loop-Fallback live gesmoked.

## Echte APIs anbinden

Die lokalen Rollen liegen in `src/orchestrated_loop/agents.py`. Produktive Adapter
sollten dieselben JSON-kompatiblen Rueckgabeformate bedienen:

- `Researcher.ask(...)`
- `Builder.run(...)`
- `Judge.score(...)`

Damit koennen weitere Provider wie NotebookLM oder DCO-Worker hinter
die Rollen gesetzt werden, ohne den Orchestrator-Loop selbst umzubauen.

## Grenzen

- Echte Modellaufrufe nur bei explizit konfiguriertem Adapter und vorhandenem API-Key.
- Keine Secrets, keine Produktivdaten.
- Keine Schreibzugriffe ausserhalb des gewaehlten Workspaces.
- Kein autonomes Ausfuehren externer Commands ohne expliziten Adapter.
