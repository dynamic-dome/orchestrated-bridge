# Beweis-Artefakte trennen: Fake-Lauf darf Real-Beweis nicht ueberschreiben

## Kontext

Die `prove_claude_*`-Skripte koennen denselben Adapter gegen eine lokale Fake-CLI
(`-Fake`, nur Mechanik) oder eine konfigurierte Provider-CLI ausfuehren. Das
urspruengliche Builder-Skript verwendete fuer beide Modi dieselbe Ausgabesenke.

Folge (beobachtet 2026-05-30): Nach einem echten Lauf wurde ein spaeterer Fake-Lauf
gestartet; dieser ueberschrieb die Real-Ausgabe mit `mode: fake`. Die Doku (ADR 0003)
behauptete weiterhin einen erfolgreichen Real-Smoke, obwohl die lokale Ausgabe nur
den Fake belegte. Das ist ein Verifikations-Trugschluss: Eine grüne Ausgabe beweist
nicht mehr als ihren ausgewiesenen Modus.

## Entscheidung

Beweis-Artefakte werden nach Modus getrennt, damit ein billiger Mechanik-Check einen
teuren Real-Beweis nie still ueberschreibt.

- Die Skripte verwenden getrennte Ausgabesenken für Real- und Fake-Modus.
- Jeder Beweis traegt ein explizites `mode`-Feld (`real` | `fake`) — Konsumenten
  duerfen einen Beweis nur dann als Vertragsbeweis zaehlen, wenn `mode == "real"`
  UND `fallback_used == false` UND `verified == true`.
- `mode: real` ist die einzige Form, die die ADR-0003-Behauptung deckt. Ein
  `mode: fake`-Artefakt belegt ausschliesslich die Adapter-Mechanik.

## Status: GESCHLOSSEN (builder + judge)

- Die Trennung ist für builder und judge umgesetzt. Alle erzeugten
  Integrationsausgaben bleiben lokal und unversioniert, weil sie Antwortdaten,
  IDs oder lokale Umgebungsdetails enthalten können. Daher sind sie kein
  öffentlich prüfbarer Nachweis und keine Grundlage für aktuelle Provider-Claims.

## Lehre

Ein Beweisartefakt muss seinen eigenen Geltungsbereich tragen (`mode`) UND gegen
versehentliches Entwerten geschuetzt sein (getrennte Senke pro Modus). "Verified:
true" ohne `mode`-Qualifier ist mehrdeutig. Verwandt: ADR 0003, ADR 0001
(isolierter Call = kein Fallback), `verifikation-vor-aktion`.
