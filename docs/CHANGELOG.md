# Changelog — orchestrated-bridge

Neueste Eintraege oben. Format: `## [YYYY-MM-DD] Kurztitel`

---

## [2026-07-19] Produktions-Dependency DCO dokumentiert

- Abgleich orchestrated-bridge ↔ DCO ergab: der produktive DCO ruft die Engine bereits per
  Subprocess auf (`agent_run.py` → `DEFAULT_LOOP_PROJECT` = dieser Ordner) und konsumiert die
  Import-/Card-Vertraege read-only. Kein Migrationsbedarf.
- Kopplungs-Hinweis in `CLAUDE.md` + `docs/PROJECT.md` ergaenzt (State-/CLI-Vertraege nicht ohne
  DCO-Abgleich aendern). Bericht: `collections/dco-integration/2026-07-19-orchestrated-bridge-dco-alignment.md`.
- Offene Luecke: Pre-Tool-Use-Gate wird vom DCO (noch) nicht konsumiert — Designentscheidung offen.

## [2026-06-01] Projekt-Dokumentation angelegt (Regel 13)

- `CLAUDE.md` + `HOW-TO-USE.md` im Root angelegt (Namensfalle dokumentiert, Verweis-Landkarte).
- `docs/`-Skelett nach globalem Standard: PROJECT.md, ARCHITECTURE.md, CAPABILITIES.md, CHANGELOG.md.
- Bewusst NICHT dupliziert: Loop-/State-Vertrag bleibt in `README.md`, Glossar in `CONTEXT.md`,
  Gate-Operator-Doku in `docs/dual-bridge-gate.md`, Entscheidungen in `docs/adr/`.

## [2026-06-01] Gate-Policy nach Entscheidbarkeit getrennt + Security-Fix

- Zwei unabhaengige Policy-Klassen: secret-sweep (lokal-sofort, `--local-policy enforce`) vs.
  repo-write-Gate (review-beduerftig, `--shadow`). HEAD `8cf62f3`.
- Security-Fix: `shadow` lief durch das untrusted Event-Dict → injizierbarer Self-Bypass. Jetzt
  expliziter Operator-Parameter. 2 neue Tests fuer den echten Vektor. Full suite gruen.
- Konzept-Neueinordnung: synchroner Cross-Device-Review pro Tool-Call ist eine Sackgasse (ADR/CONTEXT).

## [2026-05-31] Gate Phasen 0–6 vertrags- und live-bewiesen

- secret-sweep in den Gate-Flow verdrahtet (FIRST vor is_risky, ueber die Bridge gebaut).
- Walking Skeleton ueber zwei Laptops bewiesen: rejected (git push) UND accepted (echo) real ueber die Bridge.
- 6 Live-Bugs gefixt (dead-drop Lane, Stop-Hook-Crash, Exit-Code luegt, geerbter Bad-Key, Tool-Permission-Hang, cmd.exe-Quoting).

## [2026-05-30] Loop + Adapter + DCO-Handoff Grundstand

- Orchestrator-Loop, State-/Run-Vertrag, OpenAI- + Claude-Code-Adapter, read-only DCO-Handoff/Import/Validation.
- ADRs 0001–0004 angelegt (isolierter Adapter-Call als Beweis; OpenAI-Timeout; Claude-Format-Drift; Proof-Trennung real/fake).
