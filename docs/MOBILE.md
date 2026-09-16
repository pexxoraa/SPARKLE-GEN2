# Mobile

Gen-2 provides a bounded mobile lifecycle adapter: install -> authenticate by secret reference -> execute -> persist -> reopen -> sync -> notify -> independent verify -> logout. Approval is required before the lifecycle begins, provider results must be structured observations, and no credential value is passed to models.

The software lifecycle is locally verified with an injected target. Real-device/emulator acceptance remains `EXTERNALLY_BLOCKED` until an approved target exists.
