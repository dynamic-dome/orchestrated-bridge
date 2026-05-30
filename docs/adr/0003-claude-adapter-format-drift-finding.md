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
- Isolierte Real-Smokes gegen `claude.exe` fuer `builder` und `judge` liefen ohne
  Loop-Fallback erfolgreich: `provider.name=claude-code`,
  `test_results.failed=0` bzw. `blocking=false`.

### Persistierte Real-Beweise (2026-05-30, nachgezogen)

Ein erster Durchlauf liess nur ein `mode: fake`-Artefakt in `PROOF_CLAUDE.json`
zurueck (der echte Lauf wurde durch einen spaeteren Fake-Lauf ueberschrieben) — die
Behauptung oben war damit zeitweise NICHT durch ein Artefakt gedeckt. Am 2026-05-30
nachgezogen und jetzt reproduzierbar gesichert:

- `eval/contract-proof/PROOF_CLAUDE.json` — `mode: real`, `verified: true`,
  `fallback_used: false`, `duration_ms: 104596`, `changes_count: 1`. Roher Output:
  `last_stdout_claude.json` (echtes Workspace-Reasoning, schlug einen Docstring fuer
  `src/orchestrated_loop/__main__.py` vor und verifizierte ihn per `ast.parse`).
- `eval/contract-proof/PROOF_CLAUDE_JUDGE.json` — `mode: real`, `verified: true`,
  `fallback_used: false`, `duration_ms: 37020`, `overall: 0.96`, `blocking: false`.
  Roher Output: `last_stdout_claude_judge.json` (gewichtete Scores entlang der
  uebergebenen Kriterien, kontextbezogene `next_actions`).

Reproduktion (kostet echte Tokens, laeuft ueber das lokale Abo):

```powershell
.\eval\contract-proof\prove_claude_builder.ps1   # PROOF_CLAUDE.json (mode: real)
.\eval\contract-proof\prove_claude_judge.ps1     # PROOF_CLAUDE_JUDGE.json (mode: real)
```

Echtheits-Marker (statt blindem PASS): die >30s-Latenzen (Fake = ~1s), `logs` mit
echtem Reasoning ueber den realen Code, und beim judge gewichtete statt konstanter
Scores. Der builder mutiert per Vertrag den Workspace; der judge mutiert NICHT
(verifiziert: `src/`-mtimes nach dem judge-Smoke unveraendert).

Stop-Hook-Noise ist damit parserseitig toleriert. Eine separate Hook-Unterdrueckung
ist nicht mehr noetig, solange der erste JSON-Wert vollstaendig vor dem Noise steht.

## Lehre

Fake-CLI-Tests beweisen nur Mechanik, nicht Vertragstreue gegen den echten Provider.
Genau wie beim OpenAI-Timeout (ADR 0002) deckt erst der echte Lauf das Real-Verhalten auf.
Verwandt: Verifikation-vor-Aktion, Memory L4/L8/L12.
