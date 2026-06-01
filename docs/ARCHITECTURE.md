# Architektur — orchestrated-bridge

## Ueberblick

Ein deterministischer Orchestrator-Loop zerlegt ein Ziel in Rollen-Schritte (plan → research → build →
review → improve) und schreibt einen maschinenlesbaren State-/Run-Vertrag in `state/`. Externe Provider
haengen optional als Command-Adapter hinter den drei Rollen mit Output-Vertrag. Ein Pre-Tool-Use-Gate
sitzt orthogonal darueber und prueft Tool-Aktionen, bevor sie ausgefuehrt werden.

## Komponentendiagramm

```
  Goal ─▶ Orchestrator ─▶ Plan ─▶ [Researcher] [Builder] [Judge] ─▶ Review ─▶ improvement_focus
                                        │            │         │                     │
                                   (Adapter?)   (Workspace)  (Score)            naechste Iteration
                                        │
                              Command-Adapter ─stdin/stdout JSON─▶ Provider (OpenAI / Claude CLI)

  state/*  ──read-only──▶  DCO-Handoff / Import / Validation

  Tool-Call ─▶ Pre-Tool-Use-Gate ─▶ secret-sweep? ─deny─▶ (lokal, sofort, kein Roundtrip)
                                  └▶ repo-write?  ─review─▶ Dual-Bridge (Lane A→B) ─▶ accepted|rejected
```

## Kernkomponenten

### Orchestrator-Loop
- **Datei(en):** `src/orchestrated_loop/loop.py`, `agents.py`, `run_status.py`, `final_report.py`
- **Aufgabe:** Ziel zerlegen, Rollen ausfuehren, scoren, naechste Iteration aus Review-Gaps ableiten.
- **Abhaengigkeiten:** keine externen (lokal/deterministisch), sofern kein Adapter konfiguriert.

### Adapter-Schicht
- **Datei(en):** `adapters.py`, `provider_adapters/`, `adapters.*.example.json`
- **Aufgabe:** echten Provider hinter dem Rollen-Vertrag (`ROLE_REQUIRED_KEYS`) kapseln; JSON via stdin/stdout.
- **Abhaengigkeiten:** Provider-CLI/API-Key; Fallback auf lokale Rolle moeglich (= KEIN Vertragsbeweis).

### DCO-Handoff/Import
- **Datei(en):** `dco_import.py`, `dco_validate.py`
- **Aufgabe:** read-only Importpaket + Worker-Backlog + Agent-Cards erzeugen; Handoff validieren.
- **Abhaengigkeiten:** nur `state/`-Artefakte; mutiert keine DCO-DB (`safety.mutates_dco = false`).

### Pre-Tool-Use-Gate
- **Datei(en):** `gate_cli.py`, `gate_models.py`, `gate_ledger.py`, `gate_bridge.py`, `gate_secret_sweep.py`
- **Aufgabe:** Tool-Aktion vor Ausfuehrung pruefen. Zwei getrennte Policies nach Entscheidbarkeit:
  secret-sweep (lokal, sofort deny, `--local-policy enforce`) und repo-write-Gate (Review ueber Bridge, `--shadow`).
- **Abhaengigkeiten:** append-only `state/GATE_LEDGER.jsonl`; fuer Review die Dual-Bridge-Lanes.

## Datenfluss (Gate)

1. Claude-Code PreToolUse-Hook ruft `gate_cli` mit der Tool-Aktion (Event via stdin).
2. **secret-sweep FIRST** ueber alle Tools: Secret erkannt → sofort lokal `deny`, kein Ledger-Gate-Eintrag, kein B-Roundtrip.
3. Sonst `is_risky`? → repo-write-Gate: `gate_requested` ins Ledger; im Bridge-Flow Review-Task in Lane A→B.
4. Laptop B (echter `claude -p` Reviewer, hook-frei, Abo) urteilt adversarial → `accepted` | `rejected` (fail-closed).
5. A liest das Verdikt per `gate_id`; bei jedem Reviewer-Fehler kommt `rejected`, nie faelschlich `accepted`.

## Persistenz

| Speicher | Typ | Pfad | Inhalt |
|----------|-----|------|--------|
| Run-State | JSON/JSONL/MD | `state/` (gitignored) | Goal, Plan, Tasks, Review, Manifest, Trace, Handoff |
| Gate-Ledger | append-only JSONL | `state/GATE_LEDGER.jsonl` | gate_requested / Verdikte, malformed-robust |
| Eval | JSON | `eval/round-*.json` | Score je Runde |

## Sicherheit

- shadow ist **Operator-Parameter**, nie aus dem (untrusted) Event-Dict — sonst injizierbarer Self-Bypass.
- secret-sweep ist deny-first und laeuft VOR `is_risky`, fuer ALLE Tools.
- repo-write-Gate default `--shadow` → kein Self-DoS ohne lebenden Reviewer; enforce erst nach Entscheidung.
- Workspace-Grenze: keine Schreibzugriffe ausserhalb des gewaehlten Workspaces.
- Threat-Model + Skeleton-Limitationen: `docs/dual-bridge-gate.md`.

## Deployment

Kein Produktivsystem. Lokal: `pip install -e ".[test]"`, `python -m pytest`, dann `python -m orchestrated_loop …`.
Gate wird per projekt-lokaler `.claude/settings.json` (PreToolUse-Hook) aktiviert. Details: `README.md` + `docs/dual-bridge-gate.md`.
