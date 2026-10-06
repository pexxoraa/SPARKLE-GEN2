# SPARKLE GEN-2 Architecture

SPARKLE GEN-2 is organized as a layered Personal AI / Personal OS. Existing public import paths are preserved through compatibility facades; files are not deleted as part of the redesign.

## Runtime flow

```text
Web / CLI / Mobile / Voice
        ↓
Interfaces
        ↓
Application use cases
        ↓
Agents + domain policies/contracts
        ↓
Infrastructure ports/adapters
        ↓
Gen-1 / external providers / devices / SQLite
```

`runtime.py` is the composition root. It assembles the authoritative Personal Core and injects infrastructure services.

## Packages

```text
src/sparkle_gen2/
├── domain/
│   ├── models.py
│   ├── contracts/ports.py
│   ├── entities/
│   ├── value_objects/
│   ├── policies/
│   └── errors/
├── agents/
│   ├── base.py
│   ├── personal.py
│   └── router.py
├── application/
│   ├── conversation.py
│   ├── planner.py
│   ├── validation.py
│   ├── execution/
│   │   ├── approval_service.py
│   │   └── lifecycle_service.py
│   ├── personal_os/service.py
│   ├── planning/
│   ├── knowledge/
│   ├── notifications/
│   ├── background/
│   ├── autonomy/
│   ├── interaction/
│   ├── robotics/
│   ├── voice/
│   ├── world/
│   └── system/
├── infrastructure/
│   ├── persistence/store.py
│   ├── providers/model_manager.py
│   ├── providers/voice/
│   ├── providers/nvidia_models.py
│   ├── providers/voice_providers.py
│   ├── connectors/manager.py
│   ├── connectors/catalog.py
│   ├── connectors/*_connector.py
│   ├── devices/
│   └── security/
├── interfaces/
│   ├── cli.py
│   ├── http_server.py
│   └── http/transport.py
└── web/
    └── ui/
        ├── app.js
        └── modules/
            ├── core.js
            ├── os.js
            ├── conversation.js
            ├── voice.js
            ├── os-editor.js
            ├── interactions.js
            └── bootstrap.js
```

## Responsibilities

### Domain
Pure models, contracts, policies, value objects, and domain errors. No HTTP, browser, database, or provider SDK logic.

### Agents
`PersonalAgent` is the user-facing execution orchestrator. Agent identity is independent from model identity. Lifecycle execution and approval policy are application services, not hidden inside the agent facade.

### Application
Contains user-facing use cases and bounded workflows: conversation, execution, Personal OS, planning, knowledge, learning/research, notifications, robotics, voice, world state, background work, and system orchestration.

### Infrastructure
Owns persistence, model/provider transports, connectors, devices, secrets, and external integrations. The persistence store remains the authoritative SQLite implementation behind `infrastructure.persistence.store.Gen2Store`.

### Interfaces
HTTP and CLI translate transport requests into application operations. HTTP transport concerns are isolated in `interfaces/http/transport.py`; `http_server.py` is the server adapter and compatibility surface.

### Web
The browser entrypoint is intentionally tiny. Runtime UI behavior is split into focused classic-script modules so the existing DOM/global contract remains stable without keeping one 600-line application file.

## Compatibility policy

Old root imports such as `sparkle_gen2.storage`, `sparkle_gen2.model_manager`, `sparkle_gen2.connectors`, `sparkle_gen2.personal_core`, and moved connector/device/provider modules remain as thin facades. They are compatibility boundaries, not the canonical implementation locations.

Do not delete compatibility files until every external caller is migrated and removal is explicitly approved.

## Safety boundaries

- `source_code.zip` is a protected archive and is never read, extracted, regenerated, staged, committed, or deleted by the redesign.
- Gen-1 remains behind its existing boundary.
- Execution approval remains explicit and persisted.
- Connectors, providers, and devices remain capability-scoped.
- Personal OS records remain explicit user-controlled records; conversation does not silently create them.

## Placement rule for future code

1. Start with the user-facing use case in `application/`.
2. Put stable business concepts in `domain/`.
3. Put external persistence/transport/provider/device code in `infrastructure/`.
4. Keep HTTP/CLI/browser translation in `interfaces/` or `web/`.
5. Keep `runtime.py` as the only composition root.
6. Add a compatibility facade instead of breaking an existing public import during migration.
