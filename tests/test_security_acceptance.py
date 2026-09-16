import tempfile,unittest,uuid
from pathlib import Path
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.storage import Gen2Store

class Gateway:
    def __init__(self,verified=True):self.calls=[];self.verified=verified
    def health(self):return {'available':True,'tools':['memory_write','skill_search']}
    def retrieve_context(self,*a):return {'source':'fake','rendered':'minimal'}
    def invoke(self,tool,args):self.calls.append(tool);return ToolObservation(True,tool,{'model_claim':'complete'},{'verified':self.verified,'method':'independent verifier'})

def proposal(cap,risk='LOW'):
    return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('s1','action',[cap],[],['model says done'],{},30,1)],[{'description':'model says goal complete','verification_method':'all_steps_verified'}],risk,1.0,[],'test')

class SecurityAcceptanceTests(unittest.TestCase):
    def test_model_cannot_downgrade_write_risk_or_self_approve(self):
        with tempfile.TemporaryDirectory() as d:
            g=Gateway();result=PersonalAgent(Gen2Store(Path(d)/'g.sqlite3'),g,planner=StaticPlanner(proposal('memory_write','LOW'))).start('change state')
            self.assertEqual(result['status'],'WAITING');self.assertEqual(g.calls,[]);self.assertEqual(len(result['approvals']),1)
    def test_model_completion_claim_cannot_override_failed_verification(self):
        with tempfile.TemporaryDirectory() as d:
            g=Gateway(verified=False);result=PersonalAgent(Gen2Store(Path(d)/'g.sqlite3'),g,planner=StaticPlanner(proposal('skill_search'))).start('read and verify')
            self.assertEqual(result['status'],'BLOCKED');self.assertNotEqual(result['status'],'COMPLETED')
            self.assertTrue(any(c['status']!='SATISFIED' for c in result['criteria']))
