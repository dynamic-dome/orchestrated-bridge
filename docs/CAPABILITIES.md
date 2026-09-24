# Faehigkeiten — orchestrated-bridge

## Tools & Integrationen

| Tool / Feature | Status | Seit | Beschreibung |
|----------------|--------|------|--------------|
| Orchestrator-Loop | aktiv | 2026-05 | plan→research→build→review→improve, deterministisch, resume-faehig |
| State-/Run-Vertrag | aktiv | 2026-05 | maschinenlesbares `state/` (Manifest, Status, Trace, Handoff) — siehe `README.md` |
| OpenAI-Researcher-Adapter | aktiv | 2026-05 | Responses-API hinter dem `researcher`-Vertrag (ADR 0002: innerer Timeout vs. GPT-5-Latenz) |
| Claude-Code-Adapter (builder/judge) | experimentell | 2026-05 | JSON-Rollenadapter mit lokaler Fake-CLI-Testabdeckung |
| DCO-Handoff/Import/Validation | aktiv | 2026-05 | read-only Importpaket + Worker-Backlog + Agent-Cards, mutiert keine DCO-DB |
| Pre-Tool-Use-Gate (secret-sweep) | aktiv | 2026-05-31 | deny-first lokal, `--local-policy enforce`, kein Bridge-Roundtrip |
| Pre-Tool-Use-Gate (repo-write) | experimentell | 2026-05 | Ledger-basierte Entscheidung, default `--shadow`; Transport nicht automatisch verdrahtet |
| db-safety / deploy-safety | geplant | — | weitere lokale Policies als `--local-policy enforce` |
| Stage 2b (Hook → Bridge auto) | geplant | — | heute manueller Treiber; Auto-Verdrahtung offen |
| Asynchrones Review-Backend | geplant | — | schwergewichtiges Review ohne synchronen Hook (siehe Einschraenkungen) |

Status-Werte: `aktiv`, `experimentell`, `geplant`, `deprecated`, `entfernt`

## Profile / Modi

- **Loop-Mode** (`loop.py --gate-mode {off,shadow,enforce}`) — Loop-interner Schalter; getrennt vom Hook-Shadow.
- **Gate lokal-Policy** (`--local-policy {enforce,shadow}`, default enforce) — fuer secret-sweep, ignoriert globalen `--shadow`.
- **Gate repo-write** (`--shadow`) — review-beduerftige Policy; default shadow gegen Self-DoS.

## Adapter-Vertrag

Drei Rollen mit Output-Vertrag (`ROLE_REQUIRED_KEYS`): `researcher`, `builder`, `judge`. Command-Adapter
bekommen JSON ueber stdin, liefern JSON ueber stdout, laufen ohne Shell. Details: `ADAPTERS.md`, Glossar: `CONTEXT.md`.

## Einschraenkungen

- Ein synchroner Cross-Device-Review pro Tool-Call ist wegen der Latenz nicht
  fuer interaktive Workflows geeignet.
- Echte Modellaufrufe nur bei explizit konfiguriertem Adapter + vorhandenem Key/CLI.
- Keine Secrets, keine Produktivdaten, keine Schreibzugriffe ausserhalb des Workspaces.
- Gate enforce nur nach eigener Risikoanalyse aktivieren; die Demo ist kein
  vollstaendiges Sicherheitsprodukt.
