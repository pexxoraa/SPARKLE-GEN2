import tempfile,unittest,uuid
from pathlib import Path
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.storage import Gen2Store

class FakeGen1:
    def __init__(self):self.executions=[]
    def health(self):return {'available':True,'tools':['skill_search','memory_write']}
    def retrieve_context(self,*args):return {'source':'fake','rendered':'bounded'}
    def invoke(self,tool,args):self.executions.append(tool);return ToolObservation(True,tool,{'ok':True},{'verified':True,'method':'independent fake reread'})

def p(cap):return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('step-1','bounded action',[cap],[],['verified'],{},30,1)],[{'description':'all work verified','verification_method':'all_steps_verified'}],'LOW',0.8,[],'test')

class Cycle2PolicyTests(unittest.TestCase):
    def test_approval_persists_restart_and_resumes(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'g2.sqlite3';g=FakeGen1();planner=StaticPlanner(p('memory_write'))
            first=PersonalAgent(Gen2Store(path),g,planner=planner).start('write state')
            self.assertEqual(first['status'],'WAITING');self.assertEqual(g.executions,[]);aid=first['approvals'][0]
            restarted=PersonalAgent(Gen2Store(path),g,planner=planner);restarted.decide_approval(aid,'approve')
            final=restarted.resume(first['goal_id']);self.assertEqual(final['status'],'COMPLETED');self.assertEqual(g.executions,['memory_write'])
    def test_rejected_approval_never_executes(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.sqlite3');g=FakeGen1();agent=PersonalAgent(store,g,planner=StaticPlanner(p('memory_write')))
            first=agent.start('write state');agent.decide_approval(first['approvals'][0],'reject');final=agent.resume(first['goal_id'])
            self.assertEqual(final['status'],'BLOCKED');self.assertEqual(g.executions,[])
    def test_unknown_and_shell_capabilities_fail_closed_zero_execution(self):
        for cap in ('unknown_magic','shell'):
            with self.subTest(cap=cap),tempfile.TemporaryDirectory() as d:
                g=FakeGen1();result=PersonalAgent(Gen2Store(Path(d)/'g.sqlite3'),g,planner=StaticPlanner(p(cap))).start('unsafe request')
                self.assertEqual(result['status'],'BLOCKED');self.assertEqual(g.executions,[])
