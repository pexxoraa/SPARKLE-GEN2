import tempfile,unittest,uuid
from pathlib import Path
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.devices import DeviceManager,DeviceRecord
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.robotics import RobotSafetyGateway
from sparkle_gen2.storage import Gen2Store

class Gen1:
    def health(self):return {'available':True,'tools':['skill_search']}
    def retrieve_context(self,*a):return {'source':'gen1','rendered':'old context'}
    def invoke(self,t,a):return ToolObservation(True,t,{'ok':True},{'verified':True})
class Context:
    def gather(self,q):return {'items':[{'source':'projects','value':'alpha relevant'}],'item_count':1}
class Adapter:
    def status(self):return {'ok':True}
    def invoke(self,a,p):return {'action':a,'state':'done'}
    def verify(self,a,r):return {'verified':r['action']==a,'method':'device_state_reread'}
def proposal():return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('s','read',['skill_search'],[],['ok'],{'query':'x'},30,0)],[{'description':'ok','verification_method':'all_steps_verified'}],'LOW',.9,[],'t')

class Cycle27Tests(unittest.TestCase):
    def test_personal_agent_uses_integrated_context_provider_without_bypassing_gen1(self):
        with tempfile.TemporaryDirectory() as d:
            s=Gen2Store(Path(d)/'x.db');a=PersonalAgent(s,Gen1(),planner=StaticPlanner(proposal()),context_provider=Context());r=a.start('alpha');self.assertEqual(r['status'],'COMPLETED');events=s.events(r['goal_id']);self.assertTrue(any(e['event_type']=='context_retrieved' for e in events))
    def test_device_verified_execution_requires_adapter_reread(self):
        m=DeviceManager();m.register(DeviceRecord('d','iot','CONNECTED',Adapter(),capabilities=['move']));r=m.invoke_verified('d','move',{},approved=True);self.assertTrue(r['verification']['verified'])
    def test_robot_verified_execution_preserves_estop_and_verifier(self):
        r=RobotSafetyGateway(lambda a,p:{'action':a},lambda:False,lambda a,x:{'verified':x['action']==a,'method':'robot_state'});self.assertTrue(r.execute_verified('move',{},approved=True)['verification']['verified'])
        blocked=RobotSafetyGateway(lambda a,p:{},lambda:True,lambda a,x:{'verified':True})
        with self.assertRaisesRegex(RuntimeError,'emergency_stop'):blocked.execute_verified('move',{},approved=True)
    def test_robot_cannot_claim_verified_without_independent_verifier(self):
        r=RobotSafetyGateway(lambda a,p:{'action':a},lambda:False)
        with self.assertRaisesRegex(RuntimeError,'robot_verifier'):r.execute_verified('move',{},approved=True)
if __name__=='__main__':unittest.main()
