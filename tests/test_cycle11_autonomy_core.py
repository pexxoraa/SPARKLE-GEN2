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

class FailOnceGateway(Gateway):
    def __init__(self):super().__init__(False);self.failed=False
    def invoke(self,t,a):
        self.calls.append(t)
        if not self.failed:
            self.failed=True;return ToolObservation(False,t,{'error':'permanent induced failure'},{'verified':False})
        return ToolObservation(True,t,{'ok':True},{'verified':True})

class SequencePlanner:
    def __init__(self,*plans):self.plans=list(plans);self.calls=0
    def propose(self,goal,context,available_capabilities):
        index=min(self.calls,len(self.plans)-1);self.calls+=1
        return StaticPlanner(self.plans[index]).propose(goal,context,available_capabilities)

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
    def test_retry_exhaustion_automatically_replans_once_and_completes(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.sqlite3');g=FailOnceGateway();planner=SequencePlanner(proposal('skill_search',retry=0),proposal('skill_search',retry=1));a=PersonalAgent(store,g,planner=planner,max_replans=1)
            result=a.start('recover automatically');self.assertEqual(result['status'],'COMPLETED');self.assertEqual(planner.calls,2);self.assertEqual(len(g.calls),2)
            events=[e['event_type'] for e in store.events(result['goal_id'])];self.assertEqual(events.count('replan_attempted'),1);self.assertIn('replanned',events)
            traces=store.operation_traces(trace_id=result['trace_id']);self.assertTrue(any(t['kind']=='recovery' and t['status']=='REPLAN' for t in traces));self.assertTrue(any(t['status']=='REPLAN_STARTED' for t in traces));self.assertTrue(any(t['status']=='REPLANNED' for t in traces))
    def test_automatic_replan_budget_prevents_loop(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.sqlite3');g=Gateway(fail=True);planner=SequencePlanner(proposal('skill_search',retry=0),proposal('skill_search',retry=0));result=PersonalAgent(store,g,planner=planner,max_replans=1).start('bounded replan')
            self.assertEqual(result['status'],'BLOCKED');self.assertEqual(planner.calls,2);self.assertEqual(len(g.calls),2);self.assertEqual([e['event_type'] for e in store.events(result['goal_id'])].count('replan_attempted'),1)
    def test_replan_cannot_bypass_pending_approval(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.sqlite3');a=PersonalAgent(store,Gateway(),planner=StaticPlanner(proposal('memory_write')));first=a.start('write')
            with self.assertRaisesRegex(ValueError,'pending approvals'):a.replan(first['goal_id'])

if __name__=='__main__':unittest.main()
