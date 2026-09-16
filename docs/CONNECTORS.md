# Connectors

`ConnectorManager` enforces explicitly granted scopes and separates adapters from model-visible data. Gmail, Outlook, Calendar, Drive, GitHub, browser, computer, Linux, files, mobile, ESP32, MQTT and ROS2 surfaces are registered. External accounts/targets remain `EXTERNALLY_BLOCKED` until genuine authorization or hardware is present. Credentials are never passed to planner prompts.

Connector lifecycle is explicit: discover -> authorize declared least-privilege scopes -> connect -> health/invoke -> independent adapter verification -> revoke. Revocation clears granted scopes and the adapter.
