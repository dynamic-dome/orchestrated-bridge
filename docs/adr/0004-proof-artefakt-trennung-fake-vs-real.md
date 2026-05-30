# Beweis-Artefakte trennen: Fake-Lauf darf Real-Beweis nicht ueberschreiben

## Kontext

Die `prove_claude_*`-Skripte koennen denselben Adapter gegen eine kostenlose
Fake-CLI (`-Fake`, nur Mechanik) ODER gegen die echte `claude.exe` (kostet Tokens,
echter Vertragsbeweis) fahren. Das urspruengliche `prove_claude_builder.ps1` schrieb
in BEIDEN Modi dieselbe Datei `PROOF_CLAUDE.json`.

Folge (beobachtet 2026-05-30): Nach einem echten Lauf wurde ein spaeterer Fake-Lauf
gestartet; dieser ueberschrieb den Real-Beweis mit `mode: fake`. Die Doku (ADR 0003)
behauptete weiterhin einen erfolgreichen Real-Smoke, aber das einzige persistierte
Artefakt belegte nur den Fake. Genau der Verifikations-Trugschluss aus
`verifikation-vor-aktion` / globale CLAUDE.md §4: ein gruenes Artefakt, das nicht das
beweist, was sein Name suggeriert.

## Entscheidung

Beweis-Artefakte werden nach Modus getrennt, damit ein billiger Mechanik-Check einen
teuren Real-Beweis nie still ueberschreibt.

- Das judge-Skript (`prove_claude_judge.ps1`, neu 2026-05-30) schreibt im Real-Modus
  nach `PROOF_CLAUDE_JUDGE.json`, im Fake-Modus nach `PROOF_CLAUDE_JUDGE_fake.json`.
- Jeder Beweis traegt ein explizites `mode`-Feld (`real` | `fake`) — Konsumenten
  duerfen einen Beweis nur dann als Vertragsbeweis zaehlen, wenn `mode == "real"`
  UND `fallback_used == false` UND `verified == true`.
- `mode: real` ist die einzige Form, die die ADR-0003-Behauptung deckt. Ein
  `mode: fake`-Artefakt belegt ausschliesslich die Adapter-Mechanik.

## Status: GESCHLOSSEN (builder + judge)

- judge: umgesetzt (getrennte Dateinamen) — real → `PROOF_CLAUDE_JUDGE.json`,
  fake → `PROOF_CLAUDE_JUDGE_fake.json`.
- builder: umgesetzt 2026-05-30 — real → `PROOF_CLAUDE.json`,
  fake → `PROOF_CLAUDE_fake.json`. Regressions-Beweis: ein anschliessender
  Fake-Lauf liess `PROOF_CLAUDE.json` (`mode: real`, 104596ms) unangetastet und
  schrieb stattdessen `PROOF_CLAUDE_fake.json` (`mode: fake`, ~1.1s). Der
  Ueberschreib-Unfall ist damit fuer beide Skripte nicht mehr moeglich.

## Lehre

Ein Beweisartefakt muss seinen eigenen Geltungsbereich tragen (`mode`) UND gegen
versehentliches Entwerten geschuetzt sein (getrennte Senke pro Modus). "Verified:
true" ohne `mode`-Qualifier ist mehrdeutig. Verwandt: ADR 0003, ADR 0001
(isolierter Call = kein Fallback), `verifikation-vor-aktion`.
