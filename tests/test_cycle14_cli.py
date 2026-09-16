import unittest
from sparkle_gen2.cli import format_result,normalize_request
class Cycle14CLITests(unittest.TestCase):
    def test_chat_prefix_is_natural_alias(self):self.assertEqual(normalize_request(['chat','organize','my','week']),'organize my week')
    def test_plain_request_unchanged(self):self.assertEqual(normalize_request(['organize','my','week']),'organize my week')
    def test_default_output_hides_json_and_verbose_shows_action_summary(self):
        r={'text':'done','verified':['Checked state'],'approvals':[],'gen1_approvals':[],'trace_id':'t1'}
        self.assertEqual(format_result(r,False),'done');self.assertIn('I completed:',format_result(r,True));self.assertIn('• Checked state',format_result(r,True));self.assertIn('Trace: t1',format_result(r,True))
if __name__=='__main__':unittest.main()
