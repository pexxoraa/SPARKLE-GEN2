import unittest
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.memory_orchestration import MemoryOrchestrator
from sparkle_gen2.rollback import RollbackManager
from sparkle_gen2.workflows import Gen1Workflow,ResearchExperimentWorkflow

class G:
    def health(self):return {'tools':['memory_write','research_workspace','engineering_inspect','workspace_scaffold','workspace_verify','workspace_test','workspace_package']}
    def invoke(self,t,a):
        if t=='memory_write':return ToolObservation(True,t,{'status':'pending','proposal_id':'p1'},{'verified':True},True,'p1')
        return ToolObservation(True,t,{'args':a},{'verified':True})

class Cycle10WorkflowTests(unittest.TestCase):
    def test_memory_write_requires_user_approval_and_preserves_gen1_review(self):
        m=MemoryOrchestrator(G())
        with self.assertRaises(PermissionError):m.propose('preferences','x','y')
        r=m.propose('preferences','x','y',approved=True);self.assertTrue(r['requires_gen1_approval']);self.assertEqual(r['approval_id'],'p1')
    def test_rollback_requires_strategy_and_approval_and_verification(self):
        m=RollbackManager()
        with self.assertRaises(ValueError):m.prepare('g','delete','none')
        r=m.prepare('g','change','restore snapshot')
        with self.assertRaises(PermissionError):m.execute(r.rollback_id,lambda s:{'verified':True})
        self.assertEqual(m.execute(r.rollback_id,lambda s:{'verified':True},approved=True).status,'VERIFIED')
    def test_engineering_write_operations_require_approval(self):
        w=Gen1Workflow(G());self.assertTrue(w.inspect_code('README.md')['verification']['verified'])
        with self.assertRaises(PermissionError):w.scaffold('demo',{'README.md':'demo'})
        self.assertEqual(w.scaffold('demo',{'README.md':'demo'},approved=True)['tool'],'workspace_scaffold')
    def test_research_to_experiment_records_verified_evidence(self):
        w=ResearchExperimentWorkflow(G());e=w.create_from_research('topic','hypothesis','method');self.assertEqual(e.status,'RUNNING');self.assertTrue(e.observations[0]['verification']['verified'])

if __name__=='__main__':unittest.main()
