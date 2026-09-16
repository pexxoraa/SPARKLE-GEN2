# Personal Core, PWA, and cross-device trust model

SPARKLE Gen-2 has one authoritative Personal Core. The CLI, PWA, device clients, and background worker all use the same Gen-2 stores, `PersonalAgent`, policy, approval, and verification services. The browser does not contain a second orchestration engine.

## Runtime shape

```text
PWA / device client / CLI
          |
  authenticated Personal Core API
          |
  +-------+----------+-----------+-------------+
  |                  |           |             |
Session + chat     Goals/tasks  Approvals   Notifications
  |                  |           |             |
  +---------------- PersonalAgent ------------+
                         |
          deterministic policy + permissions
                         |
               exact capability boundary
                  /                \
               Gen-1        Gen-2 environment adapters
                              (for example ROS2 sim)
                         |
             observation + independent verification
```

## Device enrollment and authentication

A device is enrolled with a single-use, short-lived pairing code. Enrollment produces a random device credential. The server stores only a SHA-256 token hash. Web clients receive the credential through an `HttpOnly; SameSite=Strict` cookie; JavaScript cannot read it. Native/device agents may use the bearer form. Revoking a device invalidates all of its stored tokens without rebuilding the Personal Core.

Device records persist identity, name, type, OS, declared capabilities, status, creation time, last seen, and revocation state. API data is capability-scoped: a device only receives conversation, task, approval, notification, or device-management state for scopes granted at enrollment.

## Network boundary

The Personal Core binds to loopback by default. A non-loopback bind is rejected unless a TLS certificate and private key are explicitly configured. Public deployment is not enabled by default. Private-network access should use authenticated private connectivity and TLS; internal workers must never be exposed merely to make the PWA reachable.

The service worker caches only the static application shell. `/api/*` and `/health` are explicitly excluded from service-worker caching. Personal state remains authoritative in the Personal Core.

## Cross-device sessions

Conversation messages are persisted by central `session_id`. Any authorized device with `conversation` scope may attach to that same session. Opening a session from another device does not clone the goal or create a separate assistant identity. Device IDs are recorded on user turns so handoff remains auditable.

## Background execution

`sparkle-background-worker` is a separate process that consumes persistent queued background tasks. The UI may close and reopen without owning task execution. The worker reconstructs the same Personal Agent and resumes only persisted work that remains eligible under normal policy and approval gates.

## User-controlled autonomy

The Personal Core persists one of `MANUAL`, `APPROVAL_REQUIRED`, `TRUSTED_ACTIONS`, or `LIMITED_AUTONOMOUS`. This is an additional ceiling for unattended operation. It can never convert deterministic `REQUIRE_APPROVAL` or `DENY` policy outcomes into `ALLOW`.

## ROS2 simulation

When explicitly configured and healthy, the environment gateway exposes only `ros2_sim_status` and `ros2_sim_move`. Status is read-only. Move is deterministic `MEDIUM` risk and requires human approval. Execution still passes through the independent ROS2 safety controller, e-stop, bounded command limits, and post-action pose re-read. This evidence is simulation-only and does not establish physical robotics capability.

## Offline/degraded behavior

The PWA shell can open from its static cache, but API state is never fabricated from stale service-worker data. When the Personal Core is unavailable, the UI reports that state. Provider/tool failures remain represented as waiting, blocked, failed, or unavailable states in the authoritative task model.

## Model behavior

The UI never exposes a model picker for normal use. Model-backed work goes only to the Nemotron-only Gen-2 registry. When Nemotron is unavailable, the UI reports degraded/waiting state; deterministic local features remain usable and no hidden model fallback occurs.
