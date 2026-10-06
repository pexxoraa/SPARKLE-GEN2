import unittest
from sparkle_gen2.default_acceptance import build_acceptance_matrix
from sparkle_gen2.required_capabilities import MASTER_REQUIRED_CAPABILITIES
class AcceptanceManifestTests(unittest.TestCase):
    def test_packaged_evidence_is_not_presented_as_a_fresh_probe(self):
        for row in build_acceptance_matrix().summary():self.assertIn('not a current runtime probe',row['evidence_source'])

    def test_all_declared_capabilities_have_terminal_classification(self):
        m=build_acceptance_matrix();self.assertEqual(m.unresolved(),[])
        states={x['capability']:x for x in m.summary()};self.assertEqual(set(states),MASTER_REQUIRED_CAPABILITIES)
        for item in states.values():
            self.assertTrue(item['evidence'])
            if item['status']=='EXTERNALLY_BLOCKED':self.assertTrue(item['dependency'])
            if item['status']=='DEFERRED':self.assertTrue(item['limitation'])
    def test_external_dependencies_are_not_claimed_live(self):
        states={x['capability']:x for x in build_acceptance_matrix().summary()}
        for name in ('mobile','ros2_robotics','source_control_push','outlook','mqtt','esp32'):
            self.assertEqual(states[name]['status'],'EXTERNALLY_BLOCKED');self.assertTrue(states[name]['dependency'])
        self.assertEqual(states['voice_stt_tts']['status'],'LIVE_VERIFIED');self.assertIn('Gemini 3.8 Live',states['voice_stt_tts']['evidence'])
        self.assertEqual(states['browser_control']['status'],'LIVE_VERIFIED');self.assertIn('HTTP 200',states['browser_control']['evidence'])
        for name in ('gmail','calendar','drive','github_connector','image_generation'):self.assertEqual(states[name]['status'],'LIVE_VERIFIED')
        for name in ('live_model_planning','semantic_multimodal','semantic_retrieval_pipeline','embedding_provider','reranking_provider','safety_model'):self.assertEqual(states[name]['status'],'LIVE_VERIFIED')
    def test_core_security_and_persistence_are_verified(self):
        states={x['capability']:x['status'] for x in build_acceptance_matrix().summary()}
        for name in ('approval_reconciliation','goal_evaluation','background_task_engine','audit_log','deterministic_security_policy'):
            self.assertEqual(states[name],'LIVE_VERIFIED')
if __name__=='__main__':unittest.main()
