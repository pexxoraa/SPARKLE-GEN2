import unittest
from sparkle_gen2.cli import format_result
from sparkle_gen2.daily_os import DailyOperatingSystem

class Cycle30Tests(unittest.TestCase):
    def test_verbose_action_report_is_human_readable_and_default_stays_natural(self):
        r={'text':'Work is not complete yet.','status':'WAITING','checked':['calendar','tasks'],'verified':['weekly plan'],'approvals':['a1'],'gen1_approvals':[],'trace_id':'t'}
        self.assertEqual(format_result(r,False),'Work is not complete yet.');out=format_result(r,True);self.assertIn('I checked:',out);self.assertIn('I completed:',out);self.assertIn('I need approval for:',out);self.assertIn('Next:',out);self.assertNotIn('{',out)
    def test_daily_os_builds_priority_brief_from_bounded_context(self):
        context={'items':[{'source':'calendar','key':'meeting','value':'deadline today','score':.9},{'source':'memory','key':'pref','value':'likes concise updates','score':.6}]}
        b=DailyOperatingSystem().from_context(context);self.assertEqual(b[0]['kind'],'calendar');self.assertGreater(b[0]['score'],b[1]['score'])
if __name__=='__main__':unittest.main()
