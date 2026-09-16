import tempfile,unittest,uuid
from pathlib import Path
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.models import ModelProvenance,PlanProposal,PlanProposalStep
from sparkle_gen2.planner import PlannerError
from sparkle_gen2.storage import Gen2Store

class Gateway:
    def __init__(self):self.calls=0
    def health(self):return {'available':True,'tools':['skill_search']}
    def retrieve_context(self,*a):return {'source':'fake','rendered':'minimal'}
    def invoke(self,t,a):return ToolObservation(True,t,{'ok':True},{'verified':True,'method':'independent'})
class FlakyPlanner:
    def __init__(self,always=False):self.calls=0;self.always=always
    def propose(self,goal,context,caps):
        self.calls+=1
        if self.always or self.calls==1:raise PlannerError('provider_timeout')
        p=PlanProposal(uuid.uuid4().hex,goal.goal_id,[PlanProposalStep('s1','read skill',['skill_search'],[],['observed'],{'query':'python'},30,1)],[{'description':'verified','verification_method':'all_steps_verified'}],'LOW',0.7,[],'now')
        return p,ModelProvenance('r1','fake','m','reasoning',['planning','reasoning'],'healthy','HEALTHY')

class PlanningRecoveryTests(unittest.TestCase):
    def test_safe_planner_retry(self):
        with tempfile.TemporaryDirectory() as d:
            planner=FlakyPlanner();r=PersonalAgent(Gen2Store(Path(d)/'g.sqlite3'),Gateway(),planner=planner,planner_retries=1).start('plan this')
            self.assertEqual(planner.calls,2);self.assertEqual(r['status'],'COMPLETED')
    def test_planner_failure_executes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            g=Gateway();planner=FlakyPlanner(always=True);r=PersonalAgent(Gen2Store(Path(d)/'g.sqlite3'),g,planner=planner,planner_retries=1).start('plan this')
            self.assertEqual(r['status'],'WAITING')
