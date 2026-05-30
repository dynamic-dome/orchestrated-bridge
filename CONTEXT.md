# orchestrated-loop

Lokaler Orchestrator-Loop, der ein Ziel in Rollen-Schritte zerlegt (plan → research →
build → review → improve) und pro Rolle optional einen externen Command-Adapter statt
der lokalen Implementierung aufruft. Erzeugt read-only Handoff-Artefakte fuer den DCO.

## Language

**Adapter-Vertrag härten**:
Beweisen, dass ein Command-Adapter mit einem ECHTEN Provider (API-Key/CLI) denselben
JSON-Rollen-Vertrag erfuellt, den die Fake-Tests pruefen. Scope = ein realer Rollen-Call,
nicht ein Ende-zu-Ende-Lauf und nicht der DCO-Worker-Pfad.
_Avoid_: Live-Smoke (überladen), End-to-End-Test, Produktiv-Smoke

**Role** (Adapter-Schicht):
Eine der drei Rollen mit definiertem Output-Vertrag in `ROLE_REQUIRED_KEYS`:
`researcher`, `builder`, `judge`. Nur diese drei haben Provider-Adapter.
_Avoid_: planner, implementer, verifier, supervisor (das ist die DCO-Schicht)

**DCO-Rolle** (Import-Schicht):
Die Übersetzung der Adapter-Rollen für den DCO-Worker-Pfad, kodiert in
`dco_import.py`: Orchestrator→planner, Researcher→researcher, Builder→implementer,
Judge→verifier, plus `supervisor`. Lebt NUR im Handoff/Import, nicht im Adapter-Vertrag.
_Avoid_: Role (ohne Qualifier — kollidiert mit der Adapter-Schicht)

**Command-Adapter**:
Ein Prozess, der JSON über stdin bekommt und den Rollen-Vertrag als JSON über stdout
zurückgibt, ohne Shell gestartet. Kapselt einen Provider hinter dem Rollen-Vertrag.
_Avoid_: Provider, Plugin, Tool

**Provider**:
Der externe Modell-Dienst hinter einem Command-Adapter (OpenAI Responses API,
Claude Code CLI). Der Adapter ist der Wrapper, der Provider ist der Dienst.
_Avoid_: Backend, Model, Engine

**Fallback**:
Wenn alle `max_attempts` eines Command-Adapters scheitern UND `fallback: true`,
läuft die lokale Rolle und das Ergebnis trägt `adapter.fallback_from = "command"`.
Ein Fallback ist KEIN Vertragsbeweis — der echte Provider wurde dann gerade NICHT verifiziert.
_Avoid_: Retry (das ist max_attempts), Recovery

**Vertragsbeweis**:
Das Artefakt, das belegt, dass ein echter Provider den Rollen-Vertrag erfüllt hat.
Primär = isolierter Adapter-Call (Payload via stdin, roher stdout-JSON gegen
`ROLE_REQUIRED_KEYS` geprüft, KEIN Loop → kein Fallback möglich). Bestätigung =
`ADAPTER_EVENTS.jsonl` zeigt `status: succeeded`, `type: command`, und das
Ergebnis trägt KEIN `fallback_from`.
_Avoid_: grüner E2E-Lauf, HTTP-200, "Test passed"
