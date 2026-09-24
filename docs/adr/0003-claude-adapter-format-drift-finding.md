# Claude-Code-Adapter bricht an aktuellem CLI-Ausgabeformat (FINDING, geschlossen)

Der `claude_code_role`-Adapter wurde gegen ein älteres `claude --output-format json`-Format
geschrieben: `parse_claude_output` (claude_code_role.py:159-172) erwartet entweder den
Rollen-Vertrag direkt ODER ein `{"result": "<rollen-json-string>"}`-Objekt. Die Fake-CLI
der Tests liefert genau dieses Format → Tests grün.

Der echte CLI-Lauf am 2026-05-30 lieferte ein ANDERES Format und der Adapter scheiterte mit
"Claude Code JSON did not contain a role result or result text." Befund aus dem rohen
stdout der echten `claude.exe` (1.x):

1. **Event-Stream statt Einzelobjekt.** Output ist ein JSON-ARRAY von Events
   (`rate_limit_event`, `system/init`, ...), kein dict mit `result`. Der Adapter macht
   `json.loads(raw)` und matcht keinen seiner zwei Zweige.
2. **BOM** am Anfang (utf-8-sig) — der Adapter liest ohne `utf-8-sig`.
3. **Hook-Verschmutzung.** Der verschachtelte `-p`-Lauf triggert die SessionEnd/Stop-Hooks
   dieser Umgebung; sie scheitern ("Prompt stop hooks are not yet supported outside REPL")
   und kippen Nicht-JSON-Text hinter das Array. `CLAUDE_CODE_DISABLE_HOOKS=1` (Zeile 136)
   verhindert das für Stop-Hooks NICHT.

## Status: GESCHLOSSEN — Vertrag gehaertet am 2026-05-30

Der Adapter wurde am 2026-05-30 gegen das beobachtete echte Format gehaertet:

- `parse_claude_output` akzeptiert JSON-Event-Arrays und extrahiert das finale
  `result`-Feld.
- Der Parser toleriert UTF-8-BOM und trailing Hook-Noise ueber `raw_decode`.
- `parse_role_json_text` extrahiert das erste gueltige Rollen-JSON-Objekt aus
  Claude-Prosa oder Code-Fence-aehnlichem Text und validiert danach weiter gegen
  `ROLE_REQUIRED_KEYS`.
- Tests decken Event-Stream, BOM/Hook-Noise und Prosa-vor-JSON ab; die alten
  Fake-CLI-Vertragstests bleiben gruen.
- Die damaligen lokalen Real-Smokes gegen `claude.exe` wurden ohne Loop-Fallback
  ausgefuehrt. Sie sind historische Beobachtungen, keine fortlaufende
  Kompatibilitaetszusage.

### Lokale Integrationsausgaben (2026-05-30, nachgezogen)

Ein erster Durchlauf liess eine Fake-Ausgabe an der Stelle einer Real-Ausgabe
zurueck. Daher trennen die Skripte lokale Fake- und Real-Ausgaben nach Modus.
Die Ausgaben werden nicht versioniert, weil sie provider- und
maschinenbezogene Antwortdaten enthalten koennen. Diese ADR verweist bewusst
nicht auf konkrete Ausgabedateien oder Werte; sie belegt keinen aktuell
verifizierbaren Live-Providerlauf.

Ein lokaler Integrationscheck kann mit den Skripten unter
`eval/contract-proof/` ausgefuehrt werden. Er erfordert eine passend
konfigurierte lokale Provider-Umgebung und ist nicht Teil der Test-Suite:

```powershell
.\eval\contract-proof\prove_claude_builder.ps1
.\eval\contract-proof\prove_claude_judge.ps1
```

Die Modus- und Verifikationsfelder einer lokalen Ausgabe duerfen nur fuer den
jeweiligen Lauf interpretiert werden. Der builder darf per Vertrag den gewaehlten
Workspace mutieren; der judge soll dies nicht tun.

Stop-Hook-Noise ist damit parserseitig toleriert. Eine separate Hook-Unterdrueckung
ist nicht mehr noetig, solange der erste JSON-Wert vollstaendig vor dem Noise steht.

## Lehre

Fake-CLI-Tests beweisen nur Mechanik, nicht Vertragstreue gegen den echten Provider.
Genau wie beim OpenAI-Timeout (ADR 0002) deckt erst der echte Lauf das Real-Verhalten auf.
Verwandt: Verifikation-vor-Aktion, Memory L4/L8/L12.
