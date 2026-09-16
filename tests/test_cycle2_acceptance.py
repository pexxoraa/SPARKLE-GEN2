import tempfile,unittest,uuid
from pathlib import Path
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.storage import Gen2Store

class StatefulGateway:
    def __init__(self,fail_second_once=False):self.calls=[];self.fail_second_once=fail_second_once
    def health(self):return {'available':True,'tools':['skill_search','memory_write']}
    def retrieve_context(self,*a):return {'source':'fake','rendered':'relevant only'}
    def invoke(self,tool,args):
        self.calls.append(tool)
        if tool=='memory_write' and self.fail_second_once:
            self.fail_second_once=False;return ToolObservation(False,tool,{'error':'temporary'},{'verified':False})
        return ToolObservation(True,tool,{'call_count':len(self.calls)},{'verified':True,'method':'state reread'})

def two_step():
    return PlanProposal(uuid.uuid4().hex,'x',[
      PlanProposalStep('inspect','Inspect current state',['skill_search'],[],['state retrieved'],{'query':'python'},30,1),
      PlanProposalStep('update','Persist approved update',['memory_write'],['inspect'],['state changed'],{},30,1),
    ],[{'description':'both actions verified','verification_method':'all_steps_verified'}],'MEDIUM',0.9,[],'test')

class Cycle2AcceptanceTests(unittest.TestCase):
    def test_cross_process_first_step_then_approval_then_resume(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'g.sqlite3';gateway=StatefulGateway();planner=StaticPlanner(two_step())
            first=PersonalAgent(Gen2Store(path),gateway,planner=planner).start('multi-step approved work')
            self.assertEqual(first['status'],'WAITING');self.assertEqual(gateway.calls,['skill_search']);aid=first['approvals'][0]
            after_restart=PersonalAgent(Gen2Store(path),gateway,planner=planner);after_restart.decide_approval(aid,'approve')
            final=after_restart.resume(first['goal_id']);self.assertEqual(final['status'],'COMPLETED');self.assertEqual(gateway.calls,['skill_search','memory_write'])
    def test_second_step_failure_retry_then_goal_verification(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'g.sqlite3';gateway=StatefulGateway(True);planner=StaticPlanner(two_step());agent=PersonalAgent(Gen2Store(path),gateway,planner=planner)
            first=agent.start('multi-step retry work');aid=first['approvals'][0];agent.decide_approval(aid,'approve')
            failed=agent.resume(first['goal_id']);self.assertEqual(failed['status'],'WAITING');self.assertNotEqual(failed['status'],'COMPLETED')
            final=agent.resume(first['goal_id']);self.assertEqual(final['status'],'COMPLETED');self.assertTrue(all(c['status']=='SATISFIED' for c in final['criteria']))
