---
project: orchestrated-bridge
status: active
started: 2026-05
stack: [Python, pytest]
repo: https://github.com/dynamic-dome/orchestrated-bridge
wiki_entity: "[[orchestrated-bridge]]"
---
# orchestrated-bridge

## Einzeiler

Zielgetriebener Orchestrator-Loop (plan → research → build → review → improve) mit optionalen
Provider-Adaptern und read-only DCO-Handoff. Ein separates Pre-Tool-Use-Gate kann riskante
Aktionen im Ledger erfassen; ein Review-Transport muss von einer Integration separat angestossen werden.

## Namensfalle

Ordner + Paket = `orchestrated-loop` / `orchestrated_loop` (Demo-Altlast). Repo = **orchestrated-bridge**.
Das gleichnamige Plugin-Repo `dynamic-dome/orchestrated-loop` ist ein ANDERES Projekt (unverwandte History).

## Aktueller Stand

Das Repository enthaelt einen lokalen, testbaren Demo-Loop und optionale
Provider-Adapter. Der Gate-Aufsatz ist ein experimenteller Bestandteil; seine
Grenzen und Rollout-Hinweise stehen in `docs/dual-bridge-gate.md`.

## Kernfaehigkeiten

Siehe [[CAPABILITIES.md]]. Kurzfassung:
- Deterministischer Orchestrator-Loop mit vier Rollen + maschinenlesbarem State-/Run-Vertrag.
- Command-Adapter fuer echte Provider (OpenAI Responses, Claude Code CLI) hinter dem Rollen-Vertrag.
- Read-only DCO-Handoff/Import/Validation (mutiert keine DCO-DB).
- Pre-Tool-Use-Gate: secret-sweep (lokal-sofort) + repo-write-Ledger fuer optionale externe Reviews.

## Offene Baustellen

- [ ] db-safety / deploy-safety als weitere lokale Policies (`--local-policy enforce`).
- [ ] Entscheidung: secret-sweep + repo-write-Gate von `--shadow` auf enforce scharfschalten.
- [ ] Asynchrones Review-Backend (NICHT als synchroner Pre-Tool-Use-Hook — die Sackgasse, siehe ADR/CONTEXT).
- [ ] Stage 2b: Hook → Bridge-Verschickung automatisch verdrahten (heute manueller Treiber).

## Abhaengigkeiten

- Python + pytest (lokal, deterministisch).
- Optional: OpenAI API-Key bzw. Claude Code CLI fuer echte Adapter.
- Optional ein kompatibler Review-Transport fuer den repo-write-Gate-Pfad.

## Beziehungen zu anderen Projekten

- Die erzeugten Handoff-Dateien koennen von einem externen Consumer read-only
  verarbeitet werden. Dieses Repository implementiert keine Queueing- oder
  Datenbankintegration.
