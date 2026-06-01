# Faehigkeiten — orchestrated-bridge

## Tools & Integrationen

| Tool / Feature | Status | Seit | Beschreibung |
|----------------|--------|------|--------------|
| Orchestrator-Loop | aktiv | 2026-05 | plan→research→build→review→improve, deterministisch, resume-faehig |
| State-/Run-Vertrag | aktiv | 2026-05 | maschinenlesbares `state/` (Manifest, Status, Trace, Handoff) — siehe `README.md` |
| OpenAI-Researcher-Adapter | aktiv | 2026-05 | Responses-API hinter dem `researcher`-Vertrag (ADR 0002: innerer Timeout vs. GPT-5-Latenz) |
| Claude-Code-Adapter (builder/judge) | aktiv | 2026-05-30 | gegen echte `claude.exe` gehaertet; isoliert gesmoked (ADR 0003: Format-Drift) |
| DCO-Handoff/Import/Validation | aktiv | 2026-05 | read-only Importpaket + Worker-Backlog + Agent-Cards, mutiert keine DCO-DB |
| Pre-Tool-Use-Gate (secret-sweep) | aktiv | 2026-05-31 | deny-first lokal, `--local-policy enforce`, kein Bridge-Roundtrip |
| Pre-Tool-Use-Gate (repo-write) | aktiv (shadow) | 2026-05-31 | Review ueber die Dual-Bridge, default `--shadow`, fail-closed |
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

- **Sackgasse (bewusst NICHT weiterverfolgt):** synchroner Cross-Device-Review *pro Tool-Call* — kollidiert
  mit der Physik (30s Hook-Timeout vs. ~180s Bridge-Latenz). Der `accepted`-Pfad bleibt als getestete
  Gate-Logik im Code, aber NICHT an den synchronen Hook gekoppelt.
- Echte Modellaufrufe nur bei explizit konfiguriertem Adapter + vorhandenem Key/CLI.
- Keine Secrets, keine Produktivdaten, keine Schreibzugriffe ausserhalb des Workspaces.
- Gate enforce bisher nur auf harmlosen Wegwerf-Workflows erprobt — nicht auf echten Repos scharf.
