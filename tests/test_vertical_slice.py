import tempfile,unittest,uuid
from pathlib import Path
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.storage import Gen2Store


def proposal(capability='skill_search',*,retry_limit=1):
    return PlanProposal(uuid.uuid4().hex,'placeholder',[PlanProposalStep('step-1','Execute bounded action',[capability],[],['state observed'],{'query':'python','limit':3} if capability=='skill_search' else {},30,retry_limit)],[{'description':'all required work independently verified','verification_method':'all_steps_verified'}],'LOW',0.9,[],'test')

class FakeGen1:
    def __init__(self,fail_once=False,tools=None): self.state={'executions':0};self.fail_once=fail_once;self.tools=tools or {'skill_search','memory_write'}
    def health(self): return {'available':True,'tools':sorted(self.tools)}
    def retrieve_context(self,request,requirements): return {'source':'fake-gen1','rendered':'minimal context'}
    def invoke(self,tool,arguments):
        if tool not in self.tools:return ToolObservation(False,tool,{'error':'unavailable'},{'verified':False})
        if self.fail_once:self.fail_once=False;return ToolObservation(False,tool,{'error':'induced'},{'verified':False})
        self.state['executions']+=1;observed=self.state['executions']
        return ToolObservation(True,tool,{'state':observed},{'verified':self.state['executions']==observed,'method':'state-reread'})

class VerticalSliceTests(unittest.TestCase):
    def test_complete_vertical_slice(self):
        with tempfile.TemporaryDirectory() as d:
            gateway=FakeGen1();store=Gen2Store(Path(d)/'g2.sqlite3');result=PersonalAgent(store,gateway,planner=StaticPlanner(proposal())).start('Organize Python learning')
            self.assertEqual(result['status'],'COMPLETED');self.assertEqual(gateway.state['executions'],1)
            self.assertTrue(all(c['status']=='SATISFIED' for c in result['criteria']))
    def test_failure_does_not_false_complete_and_can_retry(self):
        with tempfile.TemporaryDirectory() as d:
            gateway=FakeGen1(True);agent=PersonalAgent(Gen2Store(Path(d)/'g2.sqlite3'),gateway,planner=StaticPlanner(proposal()))
            first=agent.start('Do a bounded task');self.assertEqual(first['status'],'WAITING');self.assertEqual(agent.resume(first['goal_id'])['status'],'COMPLETED')
    def test_restart_recovers_persisted_goal(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'g2.sqlite3';gateway=FakeGen1(True);planner=StaticPlanner(proposal())
            first=PersonalAgent(Gen2Store(path),gateway,planner=planner).start('Do a restart-safe task')
            self.assertEqual(first['status'],'WAITING');self.assertEqual(PersonalAgent(Gen2Store(path),gateway,planner=planner).resume(first['goal_id'])['status'],'COMPLETED')
if __name__=='__main__':unittest.main()
