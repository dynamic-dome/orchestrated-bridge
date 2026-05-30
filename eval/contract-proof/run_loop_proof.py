"""Loop-Bestätigung (Teil a) für den OpenAI researcher-Adapter.

Fährt orchestrate() EINMAL mit dem echten Adapter (fallback:false) und prüft
ADAPTER_EVENTS.jsonl gegen die ADR-0001-Kriterien:
  - ein Event mit role=researcher, type=command, status=succeeded
  - das research-Resultat trägt KEIN adapter.fallback_from

Nutzung (Key muss in der Env stehen):
  python eval/contract-proof/run_loop_proof.py
Exit 0 = bestätigt, 1 = nicht bestätigt.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from orchestrated_loop.loop import orchestrate

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "adapters.openai-real.json"
PROOF = HERE / "LOOP_PROOF.json"


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("STOP: OPENAI_API_KEY not set in environment.", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="loop-proof-") as tmp:
        workspace = Path(tmp) / "workspace"
        results = orchestrate(
            workspace,
            max_iter=1,
            target=0.99,
            goal="Confirm the OpenAI researcher adapter runs inside the real loop.",
            adapter_config=CONFIG,
        )

        events_path = workspace / "state" / "ADAPTER_EVENTS.jsonl"
        events = []
        if events_path.exists():
            for line in events_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    events.append(json.loads(line))

        research = results["iterations"][0]["research"]
        adapter_meta = research.get("adapter", {})

        succeeded = [
            e for e in events
            if e.get("role") == "researcher"
            and e.get("type") == "command"
            and e.get("status") == "succeeded"
        ]
        fallback_used = "fallback_from" in adapter_meta

        confirmed = bool(succeeded) and not fallback_used and adapter_meta.get("type") == "command"

        proof = {
            "confirmed": confirmed,
            "succeeded_events": len(succeeded),
            "total_events": len(events),
            "adapter_type": adapter_meta.get("type"),
            "fallback_used": fallback_used,
            "provider": research.get("provider", {}).get("name"),
            "response_id": research.get("provider", {}).get("response_id"),
            "duration_ms_first_event": succeeded[0].get("duration_ms") if succeeded else None,
        }
        PROOF.write_text(json.dumps(proof, indent=2), encoding="utf-8")

        print(json.dumps(proof, indent=2))
        if confirmed:
            print("LOOP-CONFIRM PASS: researcher command-adapter succeeded inside orchestrate(), no fallback.")
            return 0
        print("LOOP-CONFIRM FAIL: see LOOP_PROOF.json", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
