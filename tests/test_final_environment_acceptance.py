"""The environment wrapper must preserve the complete native execution boundary."""
import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from sparkle_gen2.environment_gateway import EnvironmentGateway


class FinalEnvironmentAcceptanceTests(unittest.TestCase):
    def test_optional_ros_environment_preserves_specialists_and_artifacts(self):
        system = SimpleNamespace(artifacts=object(), interactions=object())
        base = Mock()
        base.system = system
        gateway = EnvironmentGateway(base)
        self.assertIs(gateway.system, system)
        for name in ('specialist_catalog', 'specialist_limits'):
            expected = getattr(base, name).return_value
            self.assertIs(getattr(gateway, name)(), expected)
            getattr(base, name).assert_called_once_with()
        for name in ('package_source_identity', 'validate_delegated_action_preconditions', 'verify_delegated_action'):
            expected = getattr(base, name).return_value
            self.assertIs(getattr(gateway, name)('request', authorization='exact-grant'), expected)
            getattr(base, name).assert_called_once_with('request', authorization='exact-grant')
        self.assertIn('authorization', inspect.signature(gateway.delegate_specialists).parameters)
        gateway.delegate_specialists('request', ['coding'], user_id='user', input_source='audit', authorization='exact-grant')
        base.delegate_specialists.assert_called_once_with('request', ['coding'], user_id='user', input_source='audit', authorization='exact-grant')

    def test_native_authorization_failure_is_not_swallowed(self):
        base = Mock()
        base.delegate_specialists.side_effect = PermissionError('native_authorization_denied')
        with self.assertRaisesRegex(PermissionError, 'native_authorization_denied'):
            EnvironmentGateway(base).delegate_specialists('bounded', ['coding'], user_id='user', input_source='audit', authorization=None)
