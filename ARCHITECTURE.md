# SPARKLE GEN-2 Architecture

## Goal

SPARKLE is a personal AI operating system. The codebase is organized so a developer can find a feature by responsibility without reading a giant central file.

## Dependency direction

```text
Interfaces
    ↓
Application
    ↓
Agents
    ↓
Domain
    ↓
Infrastructure
```

`runtime.py` is the only composition root. It wires infrastructure into application services and agents.

## Package map

```text
src/sparkle_gen2/
├── agents/
│   ├── base.py                 # tiny agent contract
│   ├── personal.py             # Personal Agent execution/orchestration
│   └── ...                     # specialist agents and agent registry
│
├── application/
│   ├── conversation.py         # conversation use cases
│   ├── planner.py              # planning
│   ├── validation.py           # plan validation
│   ├── learning_orchestration.py
│   ├── research_pipeline.py
│   ├── memory_orchestration.py
│   ├── automation_orchestration.py
│   ├── context_engine.py
│   ├── context_sources.py
│   └── retrieval.py
│
├── infrastructure/
│   ├── storage.py              # SQLite persistence
│   └── model_manager.py        # provider/model routing
│
├── interfaces/
│   ├── cli.py                  # CLI adapter
│   └── http_server.py          # Personal Core HTTP adapter
│
├── domain/
│   # domain contracts are currently retained in root compatibility modules;
│   # migration continues without breaking the existing public API.
│
├── runtime.py                  # composition root
├── models.py                   # domain models / compatibility API
└── compatibility modules       # old imports kept stable during migration
```

## Important boundaries

### Agent layer

An agent is a capability/persona/orchestration boundary. It is **not** a model provider.

```text
Agent → capability policy → model router → provider
```

Users can select an agent independently from a model.

### Application layer

Application services answer questions such as:

- How do I send a conversation turn?
- How do I plan a goal?
- How do I assess learning progress?
- How do I run a research workflow?
- How do I retrieve personal context?

They should not know HTTP details or browser UI details.

### Infrastructure layer

Infrastructure owns persistence, external model transports, connectors, devices, files, and other implementation details.

### Interface layer

Interfaces translate HTTP/CLI/mobile/voice requests into application calls. Business logic does not belong here.

### Runtime

`runtime.py` constructs the dependency graph once. This prevents every interface from having its own slightly different SPARKLE configuration.

## Compatibility policy

The old imports remain available temporarily:

```python
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.conversations import ConversationService
from sparkle_gen2.personal_core import PersonalCore
```

New code should use:

```python
from sparkle_gen2.agents.personal import PersonalAgent
from sparkle_gen2.application.conversation import ConversationService
from sparkle_gen2.interfaces.http_server import PersonalCore
```

This lets the architecture change without breaking the current Gen-2 test suite or external entry points.

## Rules for future code

1. Do not add business logic to `interfaces/`.
2. Do not put persistence code in agents/application services.
3. Do not make an agent directly call a provider SDK.
4. Do not make model selection decide which agent is active.
5. New features belong in the smallest responsible package.
6. Keep files focused; prefer small services over another giant core file.
7. Preserve explicit user control for user-facing Tasks, Goals, Projects, Learning, Skills, and Research records.
8. Keep Gen-1 behind a stable execution boundary.
9. Keep `source_code.zip` completely outside the redesign.

## Migration strategy

The architecture is being migrated in slices rather than through a destructive rewrite:

1. Secure checkpoint.
2. Introduce package boundaries.
3. Move implementations into canonical packages.
4. Keep compatibility shims.
5. Add tests for each boundary.
6. Migrate callers to canonical imports.
7. Remove shims only after the complete test suite and entry points are green.
