import unittest

from sparkle_gen2.agent_registry import AgentRegistry


class AgentRegistryTests(unittest.TestCase):
    def test_default_catalog_contains_core_specialized_agents(self):
        registry = AgentRegistry()
        ids = {row['agent_id'] for row in registry.list(conversation_only=True)}
        self.assertTrue({'personal', 'research', 'learning', 'engineering', 'projects', 'skills'} <= ids)

    def test_agent_and_model_are_separate_concepts(self):
        registry = AgentRegistry()
        research = registry.get('research')
        self.assertEqual(research.specialist_names, ('research',))
        self.assertIn('planning', research.preferred_model_capabilities)
        self.assertNotIn('model_id', research.to_dict())

    def test_unknown_agent_fails_closed(self):
        with self.assertRaises(KeyError):
            AgentRegistry().get('does-not-exist')


if __name__ == '__main__':
    unittest.main()
