import unittest
from sparkle_gen2.environment_gateway import EnvironmentGateway
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.policy import PolicyEngine
class Base:
    def health(self):return {'tools':['calculator'],'tool_definitions':[{'name':'calculator','description':'x','parameters':{}}]}
    def invoke(self,t,a):return ToolObservation(True,t,{'value':1},{'verified':True})
    def retrieve_context(self,*a):return {}
    def plan(self,*a):return {}
    def approval_status(self,*a):return {}
class ROS:
    def health(self):return {'ok':True}
    def invoke(self,op,p):return {'operation':op,'pose':{'x':1,'y':2}} if op=='status' else {'operation':'move','after':{'x':1.2,'y':2},'before':{'x':1,'y':2}}
    def verify(self,op,r):return {'verified':True,'method':'reread'}
class Cycle39Tests(unittest.TestCase):
    def test_composite_adds_only_live_typed_tools_and_preserves_base(self):
        g=EnvironmentGateway(Base(),ros2=ROS());h=g.health();self.assertIn('calculator',h['tools']);self.assertIn('ros2_sim_move',h['tools']);self.assertTrue(g.invoke('ros2_sim_status',{}).verification['verified']);self.assertEqual(g.invoke('calculator',{}).output['value'],1)
    def test_move_is_deterministically_approval_gated(self):
        p,r=PolicyEngine().evaluate('ros2_sim_move','user','move simulation','now');self.assertEqual(p.effect.value,'REQUIRE_APPROVAL');self.assertEqual(r.level.value,'MEDIUM')
if __name__=='__main__':unittest.main()
