import tempfile,unittest
from pathlib import Path
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.personal_data import PersonalDataOrchestrator
from sparkle_gen2.workflows import Gen1Workflow,ResearchExperimentWorkflow

SCHEMAS={
 'project_tasks':{'project'},'learning_progress':{'course'},'research_workspace':{'project','report'},
 'engineering_inspect':{'operation','path'},'workspace_scaffold':{'project_name','files','approved'},
 'workspace_verify':{'project_name','checks','approved'},'workspace_test':{'project_name','approved'},'workspace_package':{'project_name','approved'},
}
class ContractGateway:
    def __init__(self):self.calls=[]
    def health(self):return {'tools':['memory_search','knowledge_search','project_search',*SCHEMAS]}
    def invoke(self,t,a):
        self.calls.append((t,a))
        required=SCHEMAS.get(t)
        if required is not None and set(a)!=required:return ToolObservation(False,t,{'bad':a},{'verified':False})
        return ToolObservation(True,t,{'args':a},{'verified':True})

class Gen1SchemaContractTests(unittest.TestCase):
    def test_personal_data_uses_current_gen1_argument_contracts(self):
        g=ContractGateway();o=PersonalDataOrchestrator(g)
        o.retrieve('tasks','p');o.retrieve('learning','course');o.retrieve('research','project')
        self.assertEqual(set(g.calls[0][1]),{'project'});self.assertEqual(set(g.calls[1][1]),{'course'});self.assertEqual(set(g.calls[2][1]),{'project','report'})
    def test_engineering_workflow_uses_current_contracts(self):
        g=ContractGateway();w=Gen1Workflow(g)
        w.inspect_code('README.md');w.scaffold('demo',{'README.md':'x'},approved=True)
        w.verify_workspace('demo',[{'type':'python_compile','path':'x.py'}],approved=True);w.test_workspace('demo',approved=True);w.package_artifact('demo',approved=True)
        self.assertTrue(all(set(args)==SCHEMAS[t] for t,args in g.calls))
    def test_research_experiment_contract(self):
        g=ContractGateway();ResearchExperimentWorkflow(g).create_from_research('p','h','m');self.assertEqual(set(g.calls[0][1]),{'project','report'})

if __name__=='__main__':unittest.main()
