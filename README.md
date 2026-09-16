# SPARKLE Gen-2

SPARKLE Gen-2 is a separate personal-agent application built on the certified SPARKLE Gen-1 platform. It does not copy, replace, or silently modify Gen-1.

## Implemented first vertical slice

`user request → Goal → Gen-1 context → persistent Plan/TaskRun → typed Gen-1 tool → observation → verification → persisted state → natural response`

Implemented now: `PersonalAgent`, explicit goal/step lifecycle, SQLite persistence, bounded continuation, retry without false completion, restart recovery, a narrow `Gen1Gateway`, fail-closed unknown tools, Gen-1 `skill_search` integration for the Python-learning scenario, approval-preserving Gen-1 memory proposals, and a natural CLI. JSON is opt-in with `--json`.

## Run

Gen-1 must be importable. During development:

```bash
export PYTHONPATH=/path/to/SPARKLE-GEN2/src:/path/to/SPARKLE/src
python -m sparkle_gen2.cli "Organize my Python learning for this week"
```

Resume persisted work with `--resume GOAL_ID`.

## Security boundary

Gen-2 owns orchestration state only. Gen-1 remains authoritative for tools, memory/knowledge, model/provider infrastructure, authorization, execution restrictions, and audit/security controls. The local adapter invokes only tools registered in Gen-1 and passes an exact allowed-tool set. Unknown capabilities fail closed.

## Current boundary

This cycle deliberately does not implement external connectors, background workers, model-generated planning, voice, GUI, IoT, or robotics. Unsupported goals stay unresolved rather than being declared complete.
