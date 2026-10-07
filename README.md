# SPARKLE Gen-2

SPARKLE Gen-2 is a separate personal-agent application built on the certified SPARKLE Gen-1 platform. It does not copy, replace, or silently modify Gen-1.

## Cycle 2 architecture

`user goal → bounded Gen-1 context → model plan proposal → deterministic validation → Gen-2 policy/risk/approval → exact Gen-1 tool → independent observation/verification → goal criteria → natural response`

Production planning uses `Gen1PlannerModel` through Gen-1's provider-neutral `ModelRouter`. The Gen-2 product registry is capability-routed: NVIDIA Nemotron models serve planning/reasoning, multimodal, embedding, reranking and safety; FLUX serves image generation; Google Gemini 3.8 Live is the accepted production voice route; NVIDIA VoiceChat remains registered but independently gated. Every configured route keeps fallback disabled, and provider/model provenance is persisted for model calls.

Model output is only a proposal. It cannot grant permission, approve actions, execute tools, change risk policy, verify its own effects, or declare a goal complete.

## Daily use

The graphical PWA is now the primary experience. Start the private Personal Core on loopback:

```bash
export PYTHONPATH=/home/prem-macharla/SPARKLE-GEN2/src
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

The current [final live acceptance audit](docs/FINAL_LIVE_ACCEPTANCE_2026-10-07.md) maps all 33 functional areas of the supplied 44-section directive to implementation, persistence, integration, UI, tests, fresh live evidence and exact external gates. Earlier audit counts and original-document blockers are historical.
## Production-readiness boundary

Gen-2 is prepared for private local operation but is not automatically published or deployed. The authoritative persistent Gen-2 database defaults to `~/.local/share/sparkle-gen2/gen2.sqlite3`; protected provider/device configuration remains under owner-only `~/.config/sparkle/` files and is never copied into the repository. Stop Personal Core/background-worker processes cleanly before filesystem-level backup of the database and private artifact/document roots; preserve owner-only permissions on restored configuration. Schema creation is additive/idempotent at startup and external connections are re-health-checked rather than trusted from persisted state.

Operational entry points are `sparkle`/`sparkle-gen2`, `sparkle-personal-core`, and `sparkle-background-worker`. Personal Core defaults to loopback and requires configured TLS before non-loopback binding. Use the Personal Operations/diagnostics surfaces for health checks; external connectors/providers remain fail-closed when credentials, devices, or transports are absent. Upgrade/rollback must preserve the database and protected configuration separately from the source checkout; no automatic public deployment, migration destructive rewrite, or credential regeneration occurs.
