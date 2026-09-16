import tempfile,unittest,uuid
from pathlib import Path
from sparkle_gen2.connector_catalog import build_default_connectors
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.modes import AdvancedCodingMode,RoboticsEngineerMode
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.robotics import RobotSafetyGateway
from sparkle_gen2.safety_runtime import SafetyModelRuntime
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.world_model import WorldModel

class G:
    def health(self):return {'available':True,'tools':['skill_search']}
    def retrieve_context(self,*a):return {'source':'fake','rendered':''}
    def invoke(self,t,a):return ToolObservation(True,t,{'ok':True},{'verified':True})
class Workflow:
    def inspect_code(self,p):return {'tool':'engineering_inspect','path':p}
    def scaffold(self,n,f,approved=False):
        if not approved:raise PermissionError('approval_required')
        return {'tool':'workspace_scaffold'}

def proposal():return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('s1','read',['skill_search'],[],['ok'],{'query':'x'})],[{'description':'done','verification_method':'all_steps_verified'}],'LOW',.9,[],'test')

class Cycle12Tests(unittest.TestCase):
    def test_task_run_exposes_trace_id(self):
        with tempfile.TemporaryDirectory() as d:
            r=PersonalAgent(Gen2Store(Path(d)/'g.sqlite3'),G(),planner=StaticPlanner(proposal())).start('x')
            self.assertTrue(r['trace_id']);self.assertTrue(r['task_run_id'])
    def test_connector_catalog_names_all_control_surfaces(self):
        names={r['name'] for r in build_default_connectors().discover()}
        self.assertTrue({'files','linux','computer','browser','esp32','mqtt','ros2','mobile'}<=names)
    def test_safety_model_is_advisory_external_dependency(self):
        s=SafetyModelRuntime();self.assertEqual(s.health()['status'],'EXTERNALLY_BLOCKED')
        with self.assertRaises(RuntimeError):s.classify('x')
        live=SafetyModelRuntime(lambda x:{'label':'safe','score':.9});self.assertEqual(live.classify('x')['label'],'safe')
    def test_advanced_coding_and_robotics_modes_preserve_gates(self):
        c=AdvancedCodingMode(Workflow());self.assertEqual(c.inspect('x')['tool'],'engineering_inspect')
        with self.assertRaises(PermissionError):c.build('x',{})
        robot=RobotSafetyGateway(lambda a,p:{'pose':'ok'},lambda:False);world=WorldModel();mode=RoboticsEngineerMode(robot,world)
        with self.assertRaises(PermissionError):mode.move('move',{},approved=False)
        self.assertEqual(mode.move('move',{},approved=True)['pose'],'ok');self.assertIn('robot',world.nodes)

if __name__=='__main__':unittest.main()
