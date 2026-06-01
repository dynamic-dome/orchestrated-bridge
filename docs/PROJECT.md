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
Provider-Adaptern und read-only DCO-Handoff, aufgesetzt darauf ein Pre-Tool-Use-Gate, das riskante
Aktionen ueber die Dual-Bridge reviewen laesst.

## Namensfalle

Ordner + Paket = `orchestrated-loop` / `orchestrated_loop` (Demo-Altlast). Repo = **orchestrated-bridge**.
Das gleichnamige Plugin-Repo `dynamic-dome/orchestrated-loop` ist ein ANDERES Projekt (unverwandte History).

## Aktueller Stand

Aktiv. Loop + State-/Run-Vertrag stabil. Gate-Aufsatz vertrags- UND live-bewiesen (Phasen 0–6):
secret-sweep + repo-write-Gate ueber zwei Laptops via Dual-Bridge gezeigt (accepted + rejected real).
Zuletzt (2026-06-01): Gate-Policy nach Entscheidbarkeit getrennt + Security-Fix (shadow nicht mehr aus
dem Event-Dict). HEAD `8cf62f3`, alle Tests gruen. Dieses Projekt-Skelett (Regel 13) am 2026-06-01 nachgeholt.

## Kernfaehigkeiten

Siehe [[CAPABILITIES.md]]. Kurzfassung:
- Deterministischer Orchestrator-Loop mit vier Rollen + maschinenlesbarem State-/Run-Vertrag.
- Command-Adapter fuer echte Provider (OpenAI Responses, Claude Code CLI) hinter dem Rollen-Vertrag.
- Read-only DCO-Handoff/Import/Validation (mutiert keine DCO-DB).
- Pre-Tool-Use-Gate: secret-sweep (lokal-sofort) + repo-write-Gate (asynchroner Review ueber die Bridge).

## Offene Baustellen

- [ ] db-safety / deploy-safety als weitere lokale Policies (`--local-policy enforce`).
- [ ] Entscheidung: secret-sweep + repo-write-Gate von `--shadow` auf enforce scharfschalten.
- [ ] Asynchrones Review-Backend (NICHT als synchroner Pre-Tool-Use-Hook — die Sackgasse, siehe ADR/CONTEXT).
- [ ] Stage 2b: Hook → Bridge-Verschickung automatisch verdrahten (heute manueller Treiber).

## Abhaengigkeiten

- Python + pytest (lokal, deterministisch).
- Optional: OpenAI API-Key bzw. Claude Code CLI fuer echte Adapter.
- Dual-Bridge (`~/AI/dual-bridge`, Repo `dynamic-dome/dual-bridge`) fuer den Gate-Review-Pfad.

## Beziehungen zu anderen Projekten

- **Nutzt:** Dual-Bridge fuer den asynchronen Gate-Review (Laptop A ↔ B ueber Google-Drive-Lanes).
- **Wird genutzt von:** DCO (read-only Handoff-Import) — orchestrated-bridge schreibt nur in seinen Workspace.
- Teil des Knowledge-Hub `AI/Agents/` (Eltern-CLAUDE.md gilt zusaetzlich).
