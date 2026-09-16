import unittest
from sparkle_gen2.engineering_agent import AutonomousEngineeringWorkflow

class Workflow:
    def __init__(self,fail_test=False):self.calls=[];self.fail_test=fail_test
    def scaffold(self,n,f,approved=False):self.calls.append('scaffold');return {'output':{'name':n},'verification':{'verified':True}}
    def verify_workspace(self,n,c,approved=False):self.calls.append('verify');return {'output':{},'verification':{'verified':True,'method':'compile'}}
    def test_workspace(self,n,approved=False):
        self.calls.append('test')
        if self.fail_test:raise RuntimeError('tool_failed:workspace_test')
        return {'output':{},'verification':{'verified':True,'method':'worker'}}
    def package_artifact(self,n,approved=False):self.calls.append('package');return {'output':{'artifact':'x'},'verification':{'verified':True}}

class Cycle16Tests(unittest.TestCase):
    def test_requires_approval_before_any_write(self):
        w=Workflow();r=AutonomousEngineeringWorkflow(w).execute('app',{'a.py':'x=1'},[],approved=False)
        self.assertEqual(r.status,'WAITING_FOR_APPROVAL');self.assertEqual(w.calls,[])
    def test_bounded_success_requires_verified_test_before_package(self):
        w=Workflow();r=AutonomousEngineeringWorkflow(w).execute('app',{'a.py':'x=1'},[{'type':'python_compile','path':'a.py'}],approved=True)
        self.assertEqual(r.status,'COMPLETE');self.assertEqual(w.calls,['scaffold','verify','test','package'])
    def test_external_test_boundary_stops_before_package(self):
        w=Workflow(True);r=AutonomousEngineeringWorkflow(w).execute('app',{'a.py':'x=1'},[],approved=True)
        self.assertEqual(r.status,'EXTERNALLY_BLOCKED');self.assertEqual(w.calls,['scaffold','verify','test']);self.assertNotIn('package',w.calls)
    def test_operation_budget_pauses_without_overrun(self):
        w=Workflow();r=AutonomousEngineeringWorkflow(w,max_operations=2).execute('app',{'a.py':'x=1'},[],approved=True)
        self.assertEqual(r.status,'PAUSED');self.assertEqual(w.calls,['scaffold','verify'])
if __name__=='__main__':unittest.main()
