import tempfile,unittest,uuid
from pathlib import Path
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.storage import Gen2Store

class Gateway:
    def __init__(self,fail=False):self.fail=fail;self.calls=[]
    def health(self):return {'available':True,'tools':['skill_search','memory_write']}
    def retrieve_context(self,*a):return {'source':'fake','rendered':'bounded'}
    def invoke(self,t,a):
        self.calls.append(t)
        if self.fail:return ToolObservation(False,t,{'error':'induced'},{'verified':False})
        return ToolObservation(True,t,{'ok':True},{'verified':True})

def proposal(cap='skill_search',retry=1):
    return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('s1','bounded action',[cap],[],['verified'],{'query':'python'} if cap=='skill_search' else {},30,retry)],[{'description':'all verified','verification_method':'all_steps_verified'}],'LOW',.9,[],'test')

class Cycle11AutonomyCoreTests(unittest.TestCase):
    def test_cancel_persists_and_cancels_pending_approval(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.sqlite3');g=Gateway();a=PersonalAgent(store,g,planner=StaticPlanner(proposal('memory_write')))
            first=a.start('write');aid=first['approvals'][0];cancelled=a.cancel(first['goal_id'])
            self.assertEqual(cancelled['status'],'CANCELLED');self.assertEqual(store.load_approval(aid).status.value,'CANCELLED');self.assertEqual(g.calls,[])
    def test_expired_deadline_blocks_before_execution(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.sqlite3');g=Gateway();a=PersonalAgent(store,g,planner=StaticPlanner(proposal('memory_write')))
            first=a.start('write');goal=store.load_goal(first['goal_id']);goal.deadline='2000-01-01T00:00:00+00:00';store.save_goal(goal)
            result=a.resume(first['goal_id']);self.assertEqual(result['status'],'BLOCKED');self.assertEqual(g.calls,[])
    def test_replan_replaces_failed_plan_without_false_completion(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.sqlite3');g=Gateway(fail=True);a=PersonalAgent(store,g,planner=StaticPlanner(proposal('skill_search',retry=0)))
            first=a.start('read');self.assertEqual(first['status'],'BLOCKED');self.assertNotEqual(first['status'],'COMPLETED')
            g.fail=False;a.planner=StaticPlanner(proposal('skill_search',retry=1));final=a.replan(first['goal_id'])
            self.assertEqual(final['status'],'COMPLETED');self.assertTrue(all(c['status']=='SATISFIED' for c in final['criteria']))
    def test_replan_cannot_bypass_pending_approval(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.sqlite3');a=PersonalAgent(store,Gateway(),planner=StaticPlanner(proposal('memory_write')));first=a.start('write')
            with self.assertRaisesRegex(ValueError,'pending approvals'):a.replan(first['goal_id'])

if __name__=='__main__':unittest.main()
