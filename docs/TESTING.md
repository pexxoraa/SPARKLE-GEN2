# Testing

The first-cycle suite uses Python standard-library `unittest` so it does not add test dependencies to Gen-1.

Coverage includes successful state change plus re-read verification through a fake typed gateway, induced failure without false completion, retry while the goal remains alive, persisted restart recovery, live Gen-1 calculator boundary execution, and fail-closed rejection of an arbitrary-shell capability.

Live acceptance also exercises Gen-1 `skill_search` for the Python-learning scenario in an isolated `SPARKLE_DATA_DIR` and confirms an unsupported request remains unresolved.
