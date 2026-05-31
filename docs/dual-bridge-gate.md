# Pre-Tool-Use Dual-Bridge Gate — Operator Guide

> **Iteration 1 (Walking Skeleton).** This document describes the *thinnest
> end-to-end* gate: a `repo-write` policy whose verdict comes from a reviewer
> (Claude on Laptop B) over the dual-bridge. It is a **transport/ledger proof**,
> not yet a full security gate — read the Threat Model before enabling `enforce`
> on anything that matters.

**Architecture in one line:** Pre-Tool-Use is the *tripwire*, the append-only
gate ledger is the *lock*, the dual-bridge review result is the *evidence*.

A risky tool call (action N) requests a gate. The PreToolUse hook writes/checks
the gate ticket in the ledger and **denies** until a matching gate result is
`accepted`. The `gate_bridge` ships a `kind: review` task to Laptop B; B reviews
(real `claude -p`) and returns an `accepted` / `rejected` verdict; only then is
action N+1 allowed.

---

## Components

| Piece | File | Role |
|---|---|---|
| Gate models | `src/orchestrated_loop/gate_models.py` | `GateRequest` / `GateResult`, digest, ids (Phase 1) |
| Gate ledger | `src/orchestrated_loop/gate_ledger.py` | append-only JSONL lock (Phase 1) |
| Hook CLI | `src/orchestrated_loop/gate_cli.py` | the tripwire: allow/deny per ledger (Phase 2) |
| Bridge adapter | `src/orchestrated_loop/gate_bridge.py` | writes review task, collects verdict (Phase 3) |
| Loop wiring | `loop.py` `--gate-mode` | ledger + handoff/run_status metadata (Phase 4) |
| Hook snippets | `hooks/claude-pre-tool-use-gate.json` | settings.json install (Phase 5) |
| Bridge review | `../../../dual-bridge/scripts/` | `kind: review` verdict + gate_id mirror (Phase 0) |

The gate **never blocks a local loop stage** — only the PreToolUse hook blocks an
actual tool call. The loop only ensures the ledger exists and records metadata.

---

## Threat Model — read before `enforce`

**What Iteration 1 *does* protect:**

- It makes a **risky tool call deterministically pause** for an out-of-band
  (cross-device) review verdict, recorded in an append-only ledger.
- It is **fail-closed on ambiguity**: a missing/garbled reviewer verdict resolves
  to `rejected`, never `accepted`. An unknown MCP tool is gated, not waved through.
- The decision is **not bypassable from the event payload**: `gate_mode` in the
  (untrusted) hook event cannot disable the gate — shadow is operator-only
  (`--shadow` / `ORCH_GATE_MODE=shadow`).

**What Iteration 1 does NOT protect (explicit limitation — NEW4):**

> Only the `repo-write` policy exists. `secret-sweep`, `db-safety`, and
> `deploy-safety` are **NOT built**. Therefore this gate is a
> **transport/ledger proof, NOT a security gate for secret-bearing repos or
> production deploys.** Putting the skeleton into `--gate-mode enforce` on a
> secret-/deploy-critical workflow *before* those policies exist would create a
> **false sense of security**.
>
> **Rule:** Iteration-1 `enforce` only on harmless / throwaway workflows (the
> way the Stage-1 live roundtrip used dual-bridge itself as the target). Do not
> enforce on anything that touches secrets, production DBs, or live deploys
> until the secret-sweep / db-safety / deploy-safety policies land (Backlog).

**Other known risks:**

- **Drive latency ~28s p95** (measured baseline) → the gate fits build / review /
  overnight loops, *not* interactive keystroke loops.
- **Stale gate if B is offline** → the request sits unresolved; `run_status`
  reports `gate.open_count`. Resolve manually (see Stale-Gate below) or let the
  TTL (`GATE_TTL`, 2h) expire it on the next request.
- **Sibling PreToolUse hooks** in the same matcher group may still run after a
  deny (Claude Code behaviour) → keep no side-effecting sibling hooks in the
  gate's matcher group; when in doubt run `shadow`.

---

## Setup

### Laptop A (orchestrator + initiator)

1. Install the loop editable so the console entry + module run work:
   ```bash
   cd ~/AI/Agents/demos/orchestrated-loop
   python -m pip install -e ".[test]"
   ```
2. Install the Claude hook (deliberate operator step, global rule §12 — it is
   **not** auto-active). Merge the `hooks` block from
   `hooks/claude-pre-tool-use-gate.json` into your project `.claude/settings.json`
   (or `~/.claude/settings.json` for user scope). The matcher is a regex OR-list;
   `mcp__.*` gates every MCP tool.
3. Run the loop with a gate mode:
   ```bash
   python -m orchestrated_loop.loop --workspace . --gate-mode shadow   # rollout
   # later, on a harmless workflow only:
   python -m orchestrated_loop.loop --workspace . --gate-mode enforce
   ```

### Laptop B (reviewer, over dual-bridge)

Same setup as the Stage-1 live roundtrip — B is the cross-device reviewer:

```bash
# Confirm the Google-Drive mount letter; set DUAL_BRIDGE_ROOT if it differs.
export DUAL_BRIDGE_ENDPOINT=codex@laptop-b   # PowerShell: $env:DUAL_BRIDGE_ENDPOINT="codex@laptop-b"
cd ~/AI/dual-bridge/scripts
python handoff_poll.py --watch               # polls lane-A-to-B, runs the claude reviewer
```

The reviewer must end its answer with exactly one marker line —
`VERDICT: accepted` or `VERDICT: rejected` — which the bridge's review path
parses fail-closed into the result frontmatter and mirrors the `gate_id` back.

---

## Rollout: shadow → enforce

1. **shadow** first: `--gate-mode shadow`. The hook records every gate decision
   but always returns `allow` (the reason is prefixed `shadow: would deny — …`).
   No blocking. Use this to see *what would be gated* without disrupting work.
2. Inspect: `python -m orchestrated_loop.run_status --workspace .` → the `gate`
   section shows `mode`, `ledger_exists`, `open_count`.
3. **enforce** only on a harmless / throwaway workflow (Threat Model): a risky
   first action is denied with a `gate_id`, the bridge ships the review to B, and
   the action is allowed only after B returns `accepted`.

---

## Inspecting the ledger

The ledger is append-only JSONL at `state/GATE_LEDGER.jsonl`, one compact event
per line (`gate_requested` / `gate_result`). Malformed lines are ignored.

```bash
# open (unresolved) gate count comes from run_status:
python -m orchestrated_loop.run_status --workspace . | python -c "import sys,json;print(json.load(sys.stdin)['gate'])"

# raw events:
cat state/GATE_LEDGER.jsonl
```

`RUN_STATUS.md` / `RUN_STATUS.json` carry the `gate` summary; `DCO_HANDOFF.json`
`safety` carries `gate_required` / `gate_mode` / `gate_ledger`; the DCO import
worker package carries `safety.gate_policy` only when the run is gated.

## Resolving a stale gate (B offline)

A gate stuck in `requested` (B never answered) blocks its tool input until
resolved. Options:

- Bring B online and let the poller produce the verdict (normal path).
- Let it **expire**: a request older than `GATE_TTL` (2h) is treated as expired
  and the next identical action re-requests a fresh gate.
- Manual override is **intentionally not a one-flag bypass** — record a real
  `gate_result` (accepted/rejected) via the bridge, not by hand-editing the
  ledger, so the audit trail stays honest.

---

## Backlog — out of Iteration 1 (the 16 modular extensions)

Iteration 1 is the dünnste durchgehende Pfad. Deferred, in rough priority:

**Policy packs (highest first):**
1. **`secret-sweep`** — first follow-up. A pure local policy (no B roundtrip), the
   most likely thing you'll want before enforcing on a real repo. Gates tool
   inputs that would write/expose secrets.
2. `db-safety` — block writes against production DBs (ties to global rule §3).
3. `deploy-safety` — gate live-deploy actions.

**Runners (Bridge already has them; gate-consumption later):**
- `codex-worker` gate, `dco-staging-worker`, `notebooklm-research`.

**Decision backends:**
- `human-approval` (reserved as a `status: needs_owner` ledger stub).

**Operator surfaces:**
- `handoff_collect` gate render, `DCO_IMPORT` card fields.

Plus: tighter unknown-non-MCP-tool handling, full numeric/Unicode digest
normalisation (only needed if cross-layer dedupe becomes real — global rule §17).

---

## References

- **Master plan (all stages):** `~/wiki/wiki/plans/2026-05-30-dual-bridge-master-plan.md`
- **Implementation plan v2:** `~/AI/2026-05-31-pre-tool-use-dual-bridge-gate-plan-v2.md`
- **Stage 2b (full peer-review loop + overnight scheduler):** the gate brought a
  *minimal* `review → verdict` core (Phase 0); the full 2b builds on it, not beside it.
- **dual-bridge README:** `~/AI/dual-bridge/README.md` (lanes, adapters, task protocol).
