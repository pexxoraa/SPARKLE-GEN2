# SPARKLE Gen-2

SPARKLE Gen-2 is a separate personal-agent application built on the certified SPARKLE Gen-1 platform. It does not copy, replace, or silently modify Gen-1.

## Cycle 2 architecture

`user goal → bounded Gen-1 context → model plan proposal → deterministic validation → Gen-2 policy/risk/approval → exact Gen-1 tool → independent observation/verification → goal criteria → natural response`

Production planning uses `Gen1PlannerModel` through Gen-1's provider-neutral `ModelRouter`, but this release supplies a Gen-2 product registry containing exactly one active AI model: NVIDIA Nemotron 3.5 Lightning. No secondary AI model or model fallback is registered. Provider/model provenance is persisted for every model call.

Model output is only a proposal. It cannot grant permission, approve actions, execute tools, change risk policy, verify its own effects, or declare a goal complete.

## Daily use

The graphical PWA is now the primary experience. Start the private Personal Core on loopback:

```bash
export PYTHONPATH=/home/prem-macharla/SPARKLE-GEN2/src:/home/prem-macharla/SPARKLE-level3-git/src
python -m sparkle_gen2.personal_core
```

Create a temporary pairing code with `python -m sparkle_gen2.personal_core --pair`, then open the Personal Core in a browser and enroll that device. For cross-device/private-network use, configure TLS; non-loopback binding fails closed without it. Public deployment is not enabled by default.

The CLI remains available for diagnostics, administration and recovery:

```bash
python -m sparkle_gen2.cli "Check my current project"
```

Persistent background work can be supervised separately with `sparkle-background-worker` (or `python -m sparkle_gen2.background_worker_cli`).

## Current architecture and security

SPARKLE has one Personal Core, one shared session/task state, persistent device identities, capability-scoped synchronization, human approval gates, provider-neutral model routing, independent execution verification, a responsive installable PWA, and a separate persistent background worker. Environment-specific capabilities are overlaid from private runtime configuration/evidence rather than falsely baked into source defaults.

Gen-1 remains the stable execution/model/tool foundation. See `docs/ARCHITECTURE.md`, `docs/PERSONAL_CORE_UI.md`, `docs/SECURITY.md`, and `docs/ACCEPTANCE.md`.
