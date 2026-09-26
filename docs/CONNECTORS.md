# Connectors

`ConnectorManager` enforces explicitly granted scopes and separates adapters from model-visible data. Gmail, Outlook, Calendar, Drive, GitHub, browser, computer, Linux, files, mobile, ESP32, MQTT and ROS2 surfaces are registered. External accounts/targets remain `EXTERNALLY_BLOCKED` until genuine authorization or hardware is present. Credentials are never passed to planner prompts.

MQTT now uses the same trusted ConnectorManager composition pattern as Mobile/IoT/ESP32: an already-authenticated `MQTTAdapter` may be injected only with an explicit device identity and topic allowlist. Bound production adapters require positive authenticated + TLS transport health, are owner/device scoped, expose only `mqtt.read` and approval-gated `mqtt.publish`, and independently verify broker results. Without a configured broker/device adapter the production connector remains externally blocked.

Connector lifecycle is explicit: discover -> authorize declared least-privilege scopes -> connect -> health/invoke -> independent adapter verification -> revoke. Revocation clears granted scopes and the adapter.

OAuth-backed connectors use credential references only: declared scopes are bounded before connection, secret/token values remain inside the injected transport/vault, operations have independent provider verification, and revoke tears down the opaque connection. MQTT software similarly bounds topics and requires broker verification.
