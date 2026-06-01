# CLAUDE.md — orchestrated-bridge

## Projekt
Lokaler zielgetriebener Orchestrator-Loop (plan → research → build → review → improve) mit
optionalen Command-Adaptern fuer echte Provider und read-only DCO-Handoff. Aufgesetzt darauf:
ein **Pre-Tool-Use-Gate**, das riskante Aktionen ueber die Dual-Bridge asynchron reviewen laesst.

**Namensfalle (wichtig):** Ordner + Python-Paket heissen `orchestrated-loop` / `orchestrated_loop`
(Demo-Altlast). Das **Git-Repo** ist `dynamic-dome/orchestrated-bridge`. NICHT zu verwechseln mit
dem gleichnamigen Plugin-Repo `dynamic-dome/orchestrated-loop` (unverwandte History).

## Vor dem Arbeiten lesen (Reihenfolge)
1. `docs/PROJECT.md` — Zweck + aktueller Stand
2. `HOW-TO-USE.md` — Wegweiser fuer User UND Agent
3. `CONTEXT.md` — Ubiquitous Language (Glossar: Vertragsbeweis, Fallback, Provider, …)
4. `.agent-memory/session-summary.md` (Workspace-Root) — letzter Session-Stand

## Konventionen
- Sprache: Deutsch fuer Kommunikation/Doku, Englisch fuer Code/Dateinamen.
- **Keine Secrets, keine Produktivdaten** in Code/Beispielen/State.
- **Workspace-Grenze:** Builder/Adapter schreiben NUR in den gewaehlten Workspace, nie darueber hinaus.
- **Gate-Policies getrennt nach Entscheidbarkeit** (ADR 0004 + docs/dual-bridge-gate.md):
  lokal-sofort (secret-sweep, `--local-policy enforce`) vs. review-beduerftig (repo-write, `--shadow`).
- **shadow ist Operator-Parameter, nie aus dem Event-Dict** (Security-Fix, sonst injizierbarer Self-Bypass).
- **Proof-Artefakte tragen `mode: real|fake`**, getrennte Dateien (ADR 0004). Fallback ist KEIN Vertragsbeweis.

## Tests
`pip install -e ".[test]"`, dann `python -m pytest`. Isolation via `--basetemp .pytest-tmp`.
`state/` ist gitignored (Test-Ledger nicht im Repo).

## Eltern-Kontext
Liegt unter `AI/Agents/demos/` — der Knowledge-Hub-`CLAUDE.md` (eine Ebene hoeher) gilt zusaetzlich.
