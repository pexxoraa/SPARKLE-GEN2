# SPARKLE GEN-2 Architecture

## Objective

SPARKLE GEN-2 is a Personal AI / Personal OS. The architecture is designed so a developer can locate a feature by **responsibility**, not by searching a giant central file.

**Non-destructive rule:** existing files are not deleted during the redesign. Legacy paths remain available as compatibility surfaces. A file is only a candidate for removal if explicitly approved first.

## System shape

```text
                    ┌───────────────────────────┐
                    │        Interfaces         │
                    │ HTTP / CLI / Web / Voice  │
                    └─────────────┬─────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │       Application         │
                    │ use cases / orchestration  │
                    └─────────────┬─────────────┘
                                  │
              ┌───────────────────▼──────────────────┐
              │                Agents                 │
              │ identity / capability / delegation   │
              └───────────────────┬──────────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │          Domain           │
                    │ entities / policies /     │
                    │ contracts / errors        │
                    └─────────────┬─────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │      Infrastructure       │
                    │ storage / providers /     │
                    │ connectors / devices      │
                    └───────────────────────────┘

                 runtime.py = composition root
```

The dependency rule is directional:

```text
Interface → Application → Agent → Domain
                       ↘ Infrastructure ports
Infrastructure → implements those ports
```

Infrastructure details must not leak upward into domain objects.

## Repository map

```text
src/sparkle_gen2/
│
├── agents/
│   ├── base.py                 # agent contract
│   ├── personal.py             # current Personal Agent implementation
│   ├── router.py               # agent identity/selection runtime
│   ├── profiles/               # agent catalog boundary
│   └── specialists/            # specialist-agent boundary
│
├── application/
│   ├── conversation.py         # conversation use cases
│   ├── planner.py              # planning use cases
│   ├── validation.py           # plan validation
│   ├── personal_os/            # Tasks/Goals/Projects/Learning/Skills/Research
│   ├── planning/               # planning feature boundary
│   ├── execution/              # execution feature boundary
│   │   └── approval_service.py # human approval and one-time execution grants
│   ├── knowledge/              # learning/research/memory/retrieval
│   ├── system/                 # automation/system use cases
│   ├── learning_orchestration.py
│   ├── research_pipeline.py
│   ├── memory_orchestration.py
│   ├── automation_orchestration.py
│   ├── context_engine.py
│   ├── context_sources.py
│   └── retrieval.py
│
├── domain/
│   ├── models.py               # current canonical domain model set
│   ├── entities/               # entity API
│   ├── value_objects/          # enums/value-object API
│   ├── policies/               # domain policy API
│   ├── contracts/              # ports/protocols
│   └── errors/                 # stable error vocabulary
│
├── infrastructure/
│   ├── storage.py              # existing persistence implementation
│   ├── persistence/            # persistence boundary
│   ├── model_manager.py        # existing model routing implementation
│   ├── providers/              # model/provider boundary
│   ├── connectors/             # external service boundary
│   └── devices/                # device/hardware boundary
│
├── interfaces/
│   ├── cli.py                  # CLI adapter
│   ├── http_server.py           # current HTTP implementation
│   └── http/
│       ├── routes/              # feature route boundary
│       └── middleware/          # transport middleware boundary
│
├── runtime.py                  # single composition root
└── legacy root modules         # preserved compatibility APIs
```

## Responsibility rules

### 1. Domain

Domain code describes SPARKLE concepts and rules.

Examples:
- Goal
- Plan
- TaskRun
- Approval
- Permission
- RiskEvaluation
- domain errors
- capability/authorization contracts

Domain code must not import HTTP, browser, SQLite implementation details, provider SDKs, or UI code.

### 2. Application

Application code describes **what SPARKLE does**.

Examples:
- send a conversation turn
- plan a goal
- create/update an explicit Task or Goal
- assess learning
- run research
- retrieve context
- execute an automation workflow

Application services should accept domain objects/ports and return application results. They should not parse HTTP requests or manipulate browser DOM.

### 3. Agents

An agent is an identity/capability boundary.

```text
Agent
  ↓
capability policy
  ↓
application use case
  ↓
model/provider or tool
```

An agent is **not** a model.

Model selection and agent selection remain independent.

### 4. Infrastructure

Infrastructure implements technical details:
- SQLite
- model providers
- external connectors
- computer/device adapters
- ROS2 integrations
- filesystem integrations
- notifications and transports

Infrastructure can depend on domain contracts. Domain/application code should depend on stable ports rather than provider-specific implementations.

### 5. Interfaces

Interfaces translate external input into application calls:
- HTTP
- CLI
- voice
- future desktop/mobile adapters

Interfaces should contain transport concerns, not business rules.

### 6. Runtime

`runtime.py` is the composition root.

It creates:
- persistence
- Gen-1 gateway boundary
- policy
- connectors
- model routing
- context
- learning/research services
- device services
- Personal Agent
- session services

No interface should independently assemble a second SPARKLE runtime.

## Personal OS rule

Tasks, Goals, Projects, Learning, Skills and Research are explicit Personal OS records.

Normal conversation must not silently create user-facing records unless an explicit command/use case authorizes it.

The intended graph is:

```text
Goal
 └── Project
      └── Tasks
           └── Execution
                └── Evidence / Results

Learning
 └── Skills
      └── Evidence
           └── Projects / Research
```

## Compatibility rule

Existing imports remain valid while migration is underway.

Examples:

```python
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.conversations import ConversationService
from sparkle_gen2.personal_core import PersonalCore
from sparkle_gen2.models import Goal
```

Canonical new imports use the architecture packages:

```python
from sparkle_gen2.agents.personal import PersonalAgent
from sparkle_gen2.application.conversation import ConversationService
from sparkle_gen2.domain.entities import Goal
from sparkle_gen2.infrastructure.persistence import Gen2Store
```

Compatibility files are not disposable. They remain until the user explicitly approves removal.

## Web architecture

The web UI follows the same principle:

```text
web/
├── index.html
├── app.js / app.css             # compatibility entry points
└── ui/
    ├── app.js / app.css         # current UI implementation
    └── future feature modules:
        ├── core/
        ├── api/
        ├── state/
        ├── conversation/
        ├── os/
        ├── devices/
        ├── voice/
        └── components/
```

The UI should eventually make `ui/app.js` a thin bootstrap rather than another monolith.

## Migration method

The redesign is deliberately incremental:

1. Preserve a known-good Git checkpoint.
2. Introduce package boundaries.
3. Keep every existing source file.
4. Add canonical feature APIs.
5. Migrate callers one boundary at a time.
6. Add architecture/import tests.
7. Split the largest implementations only after their responsibilities are covered by tests.
8. Run focused tests after each slice.
9. Run the complete suite before each checkpoint.
10. Ask before deleting any old file.

## Current redesign priority

The largest remaining implementation hotspots are:

1. `agents/personal.py` — execution/lifecycle/memory/reporting are still combined; approval policy is now extracted.
2. `interfaces/http_server.py` — PersonalCore and feature routes are still combined; transport primitives are now extracted.
3. `infrastructure/storage.py` — persistence responsibilities need feature repositories.
4. `infrastructure/model_manager.py` — registry, health, capability routing need separation.
5. connector/device modules — need grouped infrastructure boundaries.
6. web UI — needs feature modules rather than one application file.

These are **refactoring targets, not deletion targets**.
