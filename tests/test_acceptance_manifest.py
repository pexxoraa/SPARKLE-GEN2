import unittest
from sparkle_gen2.default_acceptance import build_acceptance_matrix
class AcceptanceManifestTests(unittest.TestCase):
    def test_all_declared_capabilities_have_terminal_classification(self):
        m=build_acceptance_matrix();self.assertEqual(m.unresolved(),[]);self.assertGreaterEqual(len(m.summary()),50)
    def test_external_dependencies_are_not_claimed_live(self):
        states={x['capability']:x for x in build_acceptance_matrix().summary()}
        for name in ('live_model_planning','voice_stt_tts','gmail','browser_control','mobile','ros2_robotics','source_control_push'):
            self.assertEqual(states[name]['status'],'EXTERNALLY_BLOCKED');self.assertTrue(states[name]['dependency'])
    def test_core_security_and_persistence_are_verified(self):
        states={x['capability']:x['status'] for x in build_acceptance_matrix().summary()}
        for name in ('approval_reconciliation','goal_evaluation','background_task_engine','audit_log','deterministic_security_policy'):
            self.assertEqual(states[name],'LIVE_VERIFIED')
if __name__=='__main__':unittest.main()
