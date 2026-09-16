# Security

The model is not the security, permission, execution, device-authentication, or verification boundary.

Deterministic policy remains authoritative. Models cannot self-approve, downgrade risk, add permissions, revoke devices, bypass capability scopes, expose credentials, self-verify, or self-install improvements. State-changing actions retain approval requirements where policy requires them. User autonomy modes are an additional restriction for unattended execution and cannot override `REQUIRE_APPROVAL` or `DENY`.

## Personal Core and devices

Device pairing codes are single-use and expire. Device credentials are random and stored server-side only as hashes. Web credentials are issued in HttpOnly SameSite cookies; native/device-agent credentials use bearer authentication. Every authenticated API request re-checks current device revocation and scope. A revoked device loses all associated tokens.

The Personal Core defaults to `127.0.0.1`. Non-loopback binding requires configured TLS. No public exposure is created automatically. Static PWA assets may be cached; API and personal-state responses are not service-worker cached and API responses use `Cache-Control: no-store`.

## Execution and verification

Gen-1 ToolRegistry remains authoritative for Gen-1 tools with exact allow sets. Gen-2 environment adapters expose only typed, bounded capabilities. ROS2 simulation retains a separate safety controller, e-stop, bounded movement and independent state reread. Raw motor/GPIO paths remain denied.

The isolated workspace worker uses authenticated requests, TLS, fixed operation schemas, explicit identity, resource limits, ephemeral Bubblewrap filesystem/network isolation, hostile canaries, and signed result evidence. Unsafe process execution is not treated as isolated evidence.

Audit and lifecycle state are persisted. Hidden reasoning, raw credentials, and secret values are not exposed through the daily-use UI.
