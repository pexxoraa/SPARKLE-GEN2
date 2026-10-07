"""Additive readonly specialist mode; existing exact-write grants remain unchanged."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sparkle.contracts import ModelResponse, ToolCall
from sparkle.model import ModelAdapter
from sparkle.registry import ModelRegistry
from sparkle.system import SparkleSystem
from sparkle_gen2.delegation import DelegationRequest, SpecialistDelegationService
from sparkle_gen2.environment_gateway import EnvironmentGateway
from sparkle_gen2.gen1 import LocalGen1Gateway
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.storage import Gen2Store


class ReadonlyAdapter(ModelAdapter):
    provider = 'acceptance-test'
    model_id = 'acceptance-test'
    def __init__(self, malicious=False):
        self.malicious = malicious
        self.requests = []
    def complete(self, request):
        self.requests.append(request)
        if self.malicious and len(self.requests) == 1:
            return ModelResponse('', self.model_id, self.provider, 'tool_use', tool_calls=[ToolCall('unsafe', 'memory_write', {'content': 'must not persist'})])
        return ModelResponse('readonly analysis', self.model_id, self.provider, 'stop')
    def health(self):
        return {'configured': True}


class FinalSpecialistAcceptanceTests(unittest.TestCase):
    def make_service(self, directory, adapter):
        registry = ModelRegistry()
        registry.inject(registry.active_id, adapter)
        gateway = EnvironmentGateway(LocalGen1Gateway(SparkleSystem(model_registry=registry)))
        return SpecialistDelegationService(Gen2Store(Path(directory) / 'gen2.db'), gateway, PolicyEngine()), gateway
    def request(self, specialist='learning', **changes):
        value = dict(request_id='audit', goal_id='goal', task_run_id='run', trace_id='trace', user_id='user', capability='reasoning', specialists=[specialist], objective='Readonly analysis', read_only=True)
        value.update(changes)
        return DelegationRequest(**value)
    def test_all_native_specialists_execute_readonly_with_structured_persistence(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'SPARKLE_DATA_DIR': directory}):
            adapter = ReadonlyAdapter()
            service, gateway = self.make_service(directory, adapter)
            names = [row['name'] for row in gateway.specialist_catalog()]
            self.assertEqual(len(names), 16)
            for name in names:
                with self.subTest(specialist=name):
                    request = self.request(name, request_id='audit-' + name)
                    result = service.execute(request)
                    self.assertEqual(result.status, 'COMPLETED')
                    self.assertTrue(result.verification['verified'])
                    self.assertEqual(service.load(request.request_id).state, 'COMPLETED')
                    self.assertEqual(result.specialist_results[0]['specialist'], name)
            for request in adapter.requests:
                self.assertNotIn('memory_write', {tool.name for tool in request.tools})
                self.assertNotIn('workspace_scaffold', {tool.name for tool in request.tools})
    def test_injected_write_is_denied_even_if_model_requests_it(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'SPARKLE_DATA_DIR': directory}):
            service, gateway = self.make_service(directory, ReadonlyAdapter(malicious=True))
            result = service.execute(self.request())
            self.assertEqual(result.status, 'FAILED')
            self.assertFalse(result.verification['verified'])
            self.assertEqual(gateway.system.memory.search('must not persist'), [])
    def test_negated_memory_request_cannot_force_a_hidden_write_tool(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'SPARKLE_DATA_DIR': directory}):
            adapter = ReadonlyAdapter()
            service, gateway = self.make_service(directory, adapter)
            result = service.execute(self.request(objective='Analyze the evidence. Do not store memory.'))
            self.assertEqual(result.status, 'COMPLETED')
            self.assertIn('memory_write', gateway.system.agents.get('learning').tools)
            for request in adapter.requests:
                choice = request.tool_choice
                if isinstance(choice, dict):
                    name = choice.get('function', {}).get('name')
                    self.assertNotEqual(name, 'memory_write')
                    self.assertIn(name, {tool.name for tool in request.tools})
    def test_readonly_mode_cannot_smuggle_write_grants(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'SPARKLE_DATA_DIR': directory}):
            service, _ = self.make_service(directory, ReadonlyAdapter())
            for changes in ({'read_only': 'true'}, {'grant_id': 'forged'}, {'authorized_action': {'tool': 'memory_write', 'arguments': {}}}):
                with self.subTest(changes=changes), self.assertRaises((ValueError, PermissionError)):
                    service.prepare(self.request(**changes))
    def test_legacy_unsafe_delegation_still_requires_authority(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'SPARKLE_DATA_DIR': directory}):
            service, _ = self.make_service(directory, ReadonlyAdapter())
            with self.assertRaisesRegex(PermissionError, 'nondelegable_authority'):
                service.prepare(self.request(read_only=False))
    def test_exception_text_cannot_leak_credentials_into_delegation_records(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = Mock()
            gateway.specialist_catalog.return_value = [{'name': 'research', 'tools': ['calculator']}]
            gateway.specialist_limits.return_value = {'max_specialists': 4}
            gateway.delegate_specialists.side_effect = RuntimeError('api_key=private-acceptance-canary')
            service = SpecialistDelegationService(Gen2Store(Path(directory) / 'audit.db'), gateway, PolicyEngine())
            result = service.execute(self.request('research'))
            self.assertEqual(result.status, 'FAILED')
            self.assertEqual(result.failure['category'], 'RuntimeError')
            self.assertNotIn('private-acceptance-canary', str(service.load('audit').to_dict()))
