import tempfile,unittest,uuid
from datetime import UTC,datetime,timedelta
from pathlib import Path
from sparkle_gen2.background import BackgroundTaskService
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.failures import FailureClassifier
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.storage import Gen2Store

class Clock:
    def __init__(self):self.v=0
    def __call__(self):self.v+=1;return self.v
class WaitingAgent:
    def resume(self,g):return {'status':'WAITING','approvals':[]}
class Gate:
    def health(self):return {'available':True,'tools':['memory_write']}
    def retrieve_context(self,*a):return {'source':'x','rendered':''}
    def invoke(self,*a):return ToolObservation(True,'memory_write',{}, {'verified':True})
def proposal():return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('w','write',['memory_write'],[],['done'],{},30,0)],[{'description':'done','verification_method':'all_steps_verified'}],'MEDIUM',1,[],'x')

class Cycle18Tests(unittest.TestCase):
    def test_persisted_time_budget_stops_background_work(self):
        with tempfile.TemporaryDirectory() as d:
            st=Gen2Store(Path(d)/'x.db');c=Clock();svc=BackgroundTaskService(st,lambda:WaitingAgent(),clock=c);t=svc.create('g',max_iterations=5,time_budget_seconds=1)
            r=svc.resume(t.background_id);self.assertEqual(r.state,'WAITING');self.assertGreaterEqual(r.elapsed_seconds,1)
            r.state='QUEUED';st.save_background_task(r);r2=svc.resume(r.background_id);self.assertEqual(r2.state,'PAUSED');self.assertEqual(r2.last_error,'time_budget_exhausted')
    def test_failure_classifier_recommends_retry_then_replan(self):
        f=FailureClassifier();self.assertEqual(f.classify({'error':'provider timeout'},attempts=1,retry_limit=1).action,'RETRY');self.assertEqual(f.classify({'error':'provider timeout'},attempts=2,retry_limit=1).action,'REPLAN')
        self.assertEqual(f.classify({'error':'permission denied'},attempts=1,retry_limit=2).action,'WAIT_USER');self.assertEqual(f.classify({'error':'unsupported_tool:x'},attempts=1,retry_limit=2).action,'BLOCK')
    def test_expired_approval_cannot_be_approved(self):
        with tempfile.TemporaryDirectory() as d:
            st=Gen2Store(Path(d)/'x.db');a=PersonalAgent(st,Gate(),planner=StaticPlanner(proposal()));first=a.start('write');aid=first['approvals'][0];ap=st.load_approval(aid);ap.expires_at=(datetime.now(UTC)-timedelta(seconds=1)).isoformat();st.save_approval(ap)
            with self.assertRaisesRegex(ValueError,'expired'):a.decide_approval(aid,'approve')
            self.assertEqual(st.load_approval(aid).status.value,'EXPIRED')
if __name__=='__main__':unittest.main()
