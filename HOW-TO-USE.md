# HOW-TO-USE — orchestrated-bridge

Wegweiser fuer User UND Agent. Was liegt wo, und wo schaut man zuerst.

## Schnell-Einstieg

| Ich will… | Lies / nutze |
|-----------|--------------|
| verstehen, was das Projekt ist | `docs/PROJECT.md` |
| die Begriffe/Domaene verstehen | `CONTEXT.md` (Glossar) |
| den Loop starten / State-Vertrag | `README.md` (Schnellstart, Run-Vertrag, alle State-Dateien) |
| einen echten Provider anbinden | `README.md` → "Adapter" + `ADAPTERS.md` (Rollenvertrag) |
| die Architektur / Komponenten | `docs/ARCHITECTURE.md` |
| was das Projekt kann (Tools/Modi) | `docs/CAPABILITIES.md` |
| das Pre-Tool-Use-Gate betreiben | `docs/dual-bridge-gate.md` (Threat-Model, Modi, Operator-Doku) |
| warum eine Entscheidung so fiel | `docs/adr/` (ADR 0001–0004) |
| was sich wann aenderte | `docs/CHANGELOG.md` |

## Doku-Landkarte

- **`README.md`** — Source of Truth fuer Loop-Mechanik, Schnellstart, vollstaendigen State-/Run-Vertrag,
  Adapter-Aufrufe, DCO-Handoff/Import/Validation. (Nicht hier duplizieren — dort nachschlagen.)
- **`CONTEXT.md`** — Ubiquitous Language. Vor jeder Design-Diskussion lesen, damit Begriffe wie
  *Vertragsbeweis*, *Fallback*, *Provider*, *DCO-Rolle* konsistent benutzt werden.
- **`ADAPTERS.md`** — Command-Adapter-Vertrag (JSON via stdin/stdout, max_attempts, Fallback).
- **`docs/dual-bridge-gate.md`** — der Gate-Aufsatz: secret-sweep (lokal-sofort) + repo-write-Gate
  (review ueber die Bridge), Threat-Model, Skeleton-Limitationen.
- **`docs/adr/`** — Architecture Decision Records (isolierter Adapter-Call als Beweis;
  OpenAI-Timeout vs. GPT-5-Latenz; Claude-Adapter-Format-Drift; Proof-Artefakt-Trennung real/fake).

## Update-Regeln

- Aenderung an Loop/State-Vertrag → `README.md`.
- Neuer Begriff / geschaerfte Terminologie → `CONTEXT.md`.
- Architektur-Entscheidung mit Tragweite → neuer ADR in `docs/adr/`, Kurzverweis in `docs/CHANGELOG.md`.
- Neue Faehigkeit / Tool / Modus → `docs/CAPABILITIES.md`.
- Jeder substantielle Schritt → eine Zeile in `docs/CHANGELOG.md`.

## Qualitaetscheck vor "fertig"

1. Tests gruen: `python -m pytest` (Isolation via `--basetemp .pytest-tmp`).
2. Kein Secret / Produktivpfad in Diff oder `state/` (state/ ist gitignored).
3. Multi-Repo: chirurgisch stagen (`git add <pfad>`, kein `-A`), Bridge-Provenance nicht versehentlich committen.
