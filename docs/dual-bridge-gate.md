# Pre-Tool-Use Gate — Scope and limitations

The gate components in this repository are an experimental reference
implementation. They are intended for local evaluation and must not be treated
as a complete security control for repositories, credentials, production data,
or deployments.

## Policies

- **secret-sweep** inspects tool input locally before the regular gate decision.
  With `--local-policy enforce` it denies input matching its configured secret
  patterns. Pattern matching is a safeguard, not a substitute for secret
  management or access controls.
- **repo-write** can record a review request for risky write operations. Its
  default `--shadow` mode reports the decision without blocking. `gate_cli`
  records and checks ledger entries only; it does not instantiate
  `BridgeGateClient`, dispatch a review task, or collect a verdict. Any review
  transport must be invoked and operated separately by a deployment-specific
  integration.

## Safe evaluation

1. Run the test suite first: `python -m pytest`.
2. Start with a disposable workspace and `--gate-mode shadow`.
3. Inspect generated `state/GATE_LEDGER.jsonl` and run-status files before
   considering an enforce mode.
4. Do not use the demonstration gate as the sole control for secrets,
   production databases, live deployments, or irreversible operations.

## Operational boundaries

The project ships example hook configuration but does not activate it, configure
remote reviewers, accounts, credentials, or transport infrastructure. Configure
those components in your own environment and review their security properties
separately. A missing, malformed, or late review result must be handled according
to the deployment's explicit policy.

For implementation details, see `gate_cli.py`, `gate_secret_sweep.py`, and the
corresponding tests under `tests/`.
