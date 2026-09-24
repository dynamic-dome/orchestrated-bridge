# Adapter Contract

Der Orchestrator laeuft lokal weiter, kann aber pro Rolle externe Command-Adapter
nutzen. Ein Adapter ist ein Prozess, der JSON ueber `stdin` bekommt und JSON ueber
`stdout` zurueckgibt. Der Orchestrator startet ihn ohne Shell.

## Konfiguration

```json
{
  "researcher": {
    "type": "command",
    "command": ["python", "C:/path/to/research_adapter.py"],
    "timeout_seconds": 30,
    "max_attempts": 2,
    "fallback": true
  }
}
```

Unterstuetzte Rollen:

- `researcher`
- `builder`
- `judge`

Nicht konfigurierte Rollen laufen lokal. `max_attempts` steuert, wie oft ein
Command-Adapter bei Start-, Timeout-, Exit-Code- oder JSON-/Contract-Fehlern
versucht wird; Default ist `1`. `fallback: true` bedeutet: Wenn alle Versuche
fehlschlagen, nutzt der Orchestrator die lokale Rolle und markiert das Ergebnis mit
`adapter.fallback_from = "command"`.

## Input

Jeder Adapter bekommt ein JSON-Objekt mit mindestens:

- `role`: Rollenname
- `goal`: Zielvertrag
- `workspace`: Workspace-Pfad

Zusaetzliche Felder je Rolle:

- `researcher`: `plan`, `questions`
- `builder`: `plan`, `research`
- `judge`: `plan`, `research`, `build`, `criteria`

## Output

`researcher` muss liefern:

```json
{
  "answer": "...",
  "findings": [{"topic": "...", "detail": "..."}],
  "citations": [{"source": "...", "loc": "..."}],
  "open_questions": []
}
```

`builder` muss liefern:

```json
{
  "changes": [{"file": "...", "diff": "..."}],
  "logs": "...",
  "test_results": {"passed": 1, "failed": 0, "details": []},
  "artifacts": ["..."],
  "tasks_completed": ["I1-03"],
  "research_used": "..."
}
```

`judge` muss liefern:

```json
{
  "scores": {"planning": 1.0},
  "overall": 0.9,
  "fail_reasons": [],
  "blocking": false,
  "next_actions": []
}
```

Der Orchestrator ergaenzt selbst `adapter`-Metadaten und schreibt die aktive
Adapter-Zusammenfassung nach `state/ADAPTERS.json`. Jeder Command-Versuch wird
zusaetzlich als JSONL-Event in `state/ADAPTER_EVENTS.jsonl` protokolliert:
Rolle, Versuch, Maximalversuche, Status, Dauer und Fehlertext.

## Sicherheitsgrenzen

- Kein `shell=True`; Commands laufen als Argumentliste.
- Das Executable wird vor dem Start mit absolutem Pfad oder `shutil.which()` aufgeloest.
- Adapter bekommen keine Secrets vom Orchestrator.
- Schreibzugriffe muessen im uebergebenen `workspace` bleiben.

## OpenAI Researcher Adapter

Der erste Provider-Adapter liegt unter:

`src/orchestrated_loop/provider_adapters/openai_researcher.py`

Beispielkonfiguration:

```json
{
  "researcher": {
    "type": "command",
    "command": [
      "python",
      "-m",
      "orchestrated_loop.provider_adapters.openai_researcher"
    ],
    "timeout_seconds": 60,
    "max_attempts": 2,
    "fallback": true
  }
}
```

Runtime-Konfiguration erfolgt ueber Environment-Variablen, nicht ueber Secrets im Repo:

- `OPENAI_API_KEY` — erforderlich fuer echte OpenAI-Aufrufe.
- `ORCHESTRATED_LOOP_OPENAI_MODEL` — optional, Default `gpt-5`.
- `ORCHESTRATED_LOOP_OPENAI_ENDPOINT` — optional, Default `https://api.openai.com/v1/responses`.
- `ORCHESTRATED_LOOP_OPENAI_TIMEOUT` — optional, Default `60`.

Der Adapter nutzt die OpenAI Responses API, liest den Orchestrator-Payload aus
`stdin`, sendet Ziel, Plan und Fragen als Kontext und gibt den normalen `researcher`-
Output-Vertrag zurueck. Tests verwenden einen lokalen Fake-HTTP-Endpoint, damit keine
API-Keys oder Netzaufrufe fuer die Suite noetig sind.

## Claude Code Role Adapter

Der zweite Provider-Adapter liegt unter:

`src/orchestrated_loop/provider_adapters/claude_code_role.py`

Beispielkonfiguration:

```json
{
  "builder": {
    "type": "command",
    "command": [
      "python",
      "-m",
      "orchestrated_loop.provider_adapters.claude_code_role"
    ],
    "timeout_seconds": 300,
    "max_attempts": 2,
    "fallback": true
  },
  "judge": {
    "type": "command",
    "command": [
      "python",
      "-m",
      "orchestrated_loop.provider_adapters.claude_code_role"
    ],
    "timeout_seconds": 300,
    "max_attempts": 2,
    "fallback": true
  }
}
```

Runtime-Konfiguration:

- `ORCHESTRATED_LOOP_CLAUDE_COMMAND` - optionale JSON-Array-Basis fuer den
  Command, z.B. `["python", "C:/path/to/fake_claude.py"]`.
- `ORCHESTRATED_LOOP_CLAUDE_CMD` - optionales Einzel-Executable, Default `claude`.
- `ORCHESTRATED_LOOP_CLAUDE_MODEL` - optionales Modell fuer `--model`.
- `ORCHESTRATED_LOOP_CLAUDE_TIMEOUT` - optionaler Timeout in Sekunden, Default `300`.

Der Adapter loest das Executable mit absolutem Pfad oder `shutil.which()` auf,
startet Claude Code als `claude -p --print --output-format json`, uebergibt den
Rollenprompt ueber `stdin` und akzeptiert entweder direkt den Rollen-JSON-Vertrag
oder Claude-Code-JSON mit `{"result": "<rollen-json>"}`. Die aktuelle echte
Claude-Code-CLI kann ausserdem ein JSON-Event-Array liefern; der Adapter liest
daraus das finale `result`, toleriert BOM/trailing Hook-Noise und extrahiert ein
eingebettetes Rollen-JSON-Objekt auch dann, wenn Claude vor dem Objekt kurzen
Prosa-Text ausgibt. Tests nutzen eine lokale Fake-CLI und pruefen damit Contract,
Windows-sichere Command-Aufloesung und Fallback ohne echte Modellaufrufe.

Die Tests verwenden eine lokale Fake-CLI und pruefen damit Contract,
Windows-sichere Command-Aufloesung und Fallback ohne echte Modellaufrufe.
Die Skripte unter `eval/contract-proof/` sind nur fuer einen bewusst lokal
ausgefuehrten Integrationscheck gedacht. Ihre Ausgaben sind maschinen- und
providerbezogen und werden nicht versioniert.

## DCO-Pfad

Der gleiche Vertrag kann spaeter auf DCO-Worker gemappt werden:

1. DCO erzeugt ein Ziel und startet den Orchestrator.
2. `state/TASKS.json` bleibt die interne Work-Item-Quelle.
3. Ein Worker implementiert eine Rolle als Command-Adapter oder ersetzt den Command
   durch einen direkten Python-/MCP-Adapter.
4. `state/DCO_HANDOFF.json` dient als read-only Importvertrag fuer den DCO.
5. `state/DCO_WORKER_TASKS.json` wird daraus als externes Worker-Backlog abgeleitet.
6. `state/AGENT_CARDS.json` beschreibt Rollenprofile, Capabilities, Tools,
   erlaubte Stages, Handoff-Vertraege und Safety-Grenzen fuer DCO-Operatoren.
7. `state/TRACE.jsonl`, `state/ADAPTER_EVENTS.jsonl`, `state/REVIEW.md` und
   `state/HANDOFF.md` dienen als Audit- und Handoff-Oberflaeche.
8. `state/RUN_STATUS.json` verdichtet den Lauf fuer Operatoren und uebergeordnete
   Orchestratoren zu Status, Adaptergesundheit, DCO-Bereitschaft und empfohlener
   naechster Aktion.

Der Export mutiert keine echte DCO-Datenbank. `safety.mutates_dco` steht deshalb
explizit auf `false`.

Vor dem Import sollte der Handoff validiert werden:

```powershell
python -m orchestrated_loop.dco_validate --workspace C:\path\to\workspace
```

Der Validator schreibt `state/DCO_VALIDATION.json` und bricht mit Exit-Code 1 ab,
wenn harte Fehler gefunden werden. Der Workspace wird vor Export und Validierung
aufgeloest, sodass relative und absolute Pfadangaben denselben Handoff nicht
faelschlich invalidieren.

Nach erfolgreicher Validierung kann ein read-only Importpaket erzeugt werden:

```powershell
python -m orchestrated_loop.dco_import --workspace C:\path\to\workspace
```

Der Importer schreibt nur in den gewaehlen Workspace:

- `state/DCO_IMPORT.json`: Import-Metadaten, Validation-Report, Safety-Grenzen.
- `state/DCO_WORKER_TASKS.json`: DCO-nahes Backlog mit `planner`, `researcher`,
  `implementer`, `verifier` und `supervisor` als Rollenabbildung.
- `state/AGENT_CARDS.json`: konkrete Rollenprofile; Backlog-Tasks referenzieren
  diese Karten ueber `agent_card_ref`.
- `state/DCO_AUDIT.jsonl`: append-only Audit-Event fuer die Paket-Erzeugung.

Ist der Handoff invalid oder wuerde DCO-Mutation erlauben, bricht der Importer ab,
bevor ein Worker-Backlog geschrieben wird.

Ein externer Consumer kann dieses Paket read-only auswerten. Die Integration,
Freigaben und etwaige Queueing- oder Datenbankoperationen gehoeren bewusst nicht
zum Scope dieses Repositories.

Eine Operator-Zusammenfassung kann lokal aus allen Run-Artefakten erzeugt werden:

```powershell
python -m orchestrated_loop.run_status --workspace C:\path\to\workspace
```
