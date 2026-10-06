"""Provider-independent tool envelopes and bounded input validation."""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PermissionMetadata:
    effect: str
    authentication: str = 'owner_and_native_policy'
    scope: str = 'exact_plan_step'


@dataclass(frozen=True, slots=True)
class RiskMetadata:
    level: str
    rationale: str
    state_changing: bool
    reversibility: str = 'adapter_defined'


@dataclass(frozen=True, slots=True)
class VerificationMetadata:
    strategy: str = 'independent_adapter_observation'
    required: bool = True


@dataclass(frozen=True, slots=True)
class ToolMetadata:
    handler: str
    available: bool
    supported_agents: tuple[str, ...] = ('personal',)
    supported_models: tuple[str, ...] = ('reasoning',)


@dataclass(slots=True)
class ToolDefinition:
    tool_id: str
    name: str
    description: str
    category: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    permission: PermissionMetadata
    risk: RiskMetadata
    verification: VerificationMetadata
    metadata: ToolMetadata

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolError:
    code: str
    message: str
    retryable: bool = False


@dataclass(slots=True)
class ToolInput:
    tool_id: str
    arguments: dict[str, Any]
    owner_user_id: str
    goal_id: str
    task_run_id: str
    step_id: str


@dataclass(slots=True)
class ToolOutput:
    tool_id: str
    success: bool
    data: dict[str, Any]
    verification: dict[str, Any]
    error: ToolError | None = None
    artifacts: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def input_errors(value: Any, schema: dict[str, Any]) -> list[str]:
    """Validate the tool schema subset without including input values in errors."""
    errors: list[str] = []
    visited = 0

    def visit(item, contract, path, depth):
        nonlocal visited
        visited += 1
        if depth > 12 or visited > 2000:
            errors.append(path + ':bounds')
            return
        if not isinstance(contract, dict):
            return
        kind = contract.get('type')
        valid = {
            'object': isinstance(item, dict), 'array': isinstance(item, list),
            'string': isinstance(item, str), 'boolean': isinstance(item, bool),
            'integer': isinstance(item, int) and not isinstance(item, bool),
            'number': isinstance(item, (int, float)) and not isinstance(item, bool),
            'null': item is None,
        }
        if isinstance(kind, list):
            if not any(valid.get(k, False) for k in kind):
                errors.append(path + ':type')
                return
        elif kind in valid and not valid[kind]:
            errors.append(path + ':type')
            return
        if 'enum' in contract and item not in contract['enum']:
            errors.append(path + ':enum')
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            if not math.isfinite(item):
                errors.append(path + ':finite')
            elif ('minimum' in contract and item < contract['minimum']) or ('maximum' in contract and item > contract['maximum']):
                errors.append(path + ':range')
        if isinstance(item, str):
            if len(item) < contract.get('minLength', 0) or len(item) > contract.get('maxLength', 100000):
                errors.append(path + ':length')
            pattern = contract.get('pattern')
            if pattern and re.search(pattern, item) is None:
                errors.append(path + ':pattern')
        if isinstance(item, list):
            if len(item) < contract.get('minItems', 0) or len(item) > contract.get('maxItems', 1000):
                errors.append(path + ':items')
            for index, child in enumerate(item[:1000]):
                visit(child, contract.get('items', {}), f'{path}[{index}]', depth + 1)
        if isinstance(item, dict):
            props = contract.get('properties', {})
            for key in contract.get('required', []):
                if key not in item:
                    errors.append(path + '.' + key + ':required')
            if contract.get('additionalProperties') is False and set(item) - set(props):
                errors.append(path + ':undeclared_fields')
            if len(item) > 1000:
                errors.append(path + ':bounds')
            for key, child in list(item.items())[:1000]:
                visit(child, props.get(key, contract.get('additionalProperties', {})), path + '.' + str(key), depth + 1)

    visit(value, schema, '$', 0)
    return errors[:30]
