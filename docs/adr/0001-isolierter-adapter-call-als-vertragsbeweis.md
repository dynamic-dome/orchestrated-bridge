# Isolierter Adapter-Call als primärer Vertragsbeweis

Um zu beweisen, dass ein Command-Adapter (`openai_researcher`, `claude_code_role`)
mit einem ECHTEN Provider den Rollen-Vertrag erfüllt, wird der Adapter **isoliert**
aufgerufen — Payload direkt über stdin, roher stdout-JSON gegen `ROLE_REQUIRED_KEYS`
geprüft — NICHT über `orchestrate()`.

Grund: Beide Beispielkonfigs setzen `fallback: true`. In einem vollen Loop fällt ein
gescheiterter echter Call still auf die lokale Rolle zurück (`adapter.fallback_from =
"command"`) und produziert ein grünes Ergebnis, OHNE den Provider verifiziert zu haben.
Der isolierte Call hat keinen Loop und damit keinen Fallback-Pfad, der einen
fehlgeschlagenen echten Call kaschieren könnte. Bestätigung im echten Loop erfolgt
sekundär über `ADAPTER_EVENTS.jsonl` (`status: succeeded`, `type: command`, kein
`fallback_from`).

## Trade-off

Isolation opfert Realismus (echte Loop-Latenzen/Fehlerpfade werden nicht im Primärbeweis
getestet) zugunsten von Ehrlichkeit (kein falsch-grünes Ergebnis durch Fallback-
Verschleierung). Verwandt mit Memory L8/L12: grüner Status ≠ Vertragsbeweis.

## Konsequenz für Secrets & Kosten

- `OPENAI_API_KEY` nur als `$env:`-Variable der laufenden PowerShell-Session, nie in
  einer Datei im Repo (Subprozess erbt die Env). Nach dem Test `Remove-Item Env:\OPENAI_API_KEY`.
- Der `claude_code_role`-Adapter startet einen verschachtelten headless `claude -p`-Lauf
  (echte Tokens, Modell-Latenz, `CLAUDE_CODE_DISABLE_HOOKS=1`). Bewusster Kostenpunkt —
  nicht versehentlich im Loop auslösen.
