# Cycle 4 — platform surfaces

Implemented typed capability descriptors, a least-privilege ConnectorManager, explicit external-dependency health states, self-diagnostics, and correlated operation traces.

Connector adapters never expose credentials to models. Invocation requires an explicitly granted scope. Missing external accounts/credentials are surfaced as EXTERNALLY_BLOCKED rather than simulated.
