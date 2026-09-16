# Mobile and cross-device use

The primary cross-platform client is the responsive SPARKLE Web/PWA served by the Personal Core. The same application shell is designed for modern desktop, tablet, Android and iOS browsers. It provides conversation, task status, approvals, notifications, device management and session handoff through the central Personal Core.

A browser/PWA installation is not treated as proof of a native or physical mobile target. The separate mobile lifecycle adapter still models install -> authenticate -> execute -> persist -> reopen -> sync -> notify -> verify -> logout, and physical/emulator `mobile` acceptance remains `EXTERNALLY_BLOCKED` until a real approved target is connected and exercised.

Cross-device conversation state is central: devices attach to the same persisted `session_id`; they do not replicate the entire private database or create independent assistants. Synchronization is capability-scoped by enrolled device permissions.
