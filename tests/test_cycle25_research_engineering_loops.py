import unittest
from sparkle_gen2.engineering_agent import SoftwareEngineeringAgent
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.research_pipeline import ResearchExperimentPipeline

class Workflow:
    def __init__(self):self.tests=0;self.calls=[]
    def inspect_code(self,p):self.calls.append('inspect');return {'verification':{'verified':True}}
    def scaffold(self,n,f,approved=False,overwrite=False):self.calls.append('fix' if overwrite else 'implement');return {'verification':{'verified':True},'output':{'files':list(f)}}
    def verify_workspace(self,n,c,approved=False):self.calls.append('verify');return {'verification':{'verified':True}}
    def test_workspace(self,n,approved=False):
        self.tests+=1;self.calls.append('test')
        if self.tests==1:raise RuntimeError('tests_failed')
        return {'verification':{'verified':True}}
    def package_artifact(self,n,approved=False):self.calls.append('package');return {'verification':{'verified':True},'output':{'artifact':'a'}}
class Gen1:
    def invoke(self,t,a):return ToolObservation(True,t,{'project':a['project']},{'verified':True,'method':'persistent research store'})
def executor(spec):return {'results':{'score':.91},'metrics':{'accuracy':.91},'conclusion':'candidate supported','verification':{'verified':True,'method':'isolated worker'}}

class Cycle25Tests(unittest.TestCase):
    def test_engineering_loop_diagnoses_fixes_retests_reviews_reports(self):
        w=Workflow();a=SoftwareEngineeringAgent(w,diagnoser=lambda e:{'cause':'test'},fixer=lambda d,f:{'main.py':'fixed'},reviewer=lambda r:{'verified':True,'method':'review'})
        r=a.run('app',{'main.py':'bad'},[{'type':'python_compile','path':'main.py'}],approved=True);self.assertEqual(r['status'],'COMPLETE');self.assertEqual(r['fix_attempts'],1);self.assertIn('diagnose',r['phases']);self.assertIn('retest',r['phases']);self.assertEqual(w.calls[-1],'package')
    def test_engineering_loop_requires_approval_before_write(self):
        w=Workflow();r=SoftwareEngineeringAgent(w).run('app',{'a':'b'},[],approved=False);self.assertEqual(r['status'],'WAITING_FOR_APPROVAL');self.assertEqual(w.calls,['inspect'])
    def test_research_experiment_waits_for_approval_then_records_verified_results(self):
        p=ResearchExperimentPipeline(Gen1(),executor);wait=p.run('r1',['method-a','method-b'],'hyp','method',approved=False);self.assertEqual(wait['status'],'WAITING_FOR_APPROVAL')
        done=p.run('r1',['method-a','method-b'],'hyp','method',approved=True,project_id='p1',code_version='abc',model='m',dataset='d');self.assertEqual(done['status'],'COMPLETE');self.assertEqual(done['analysis']['metrics']['accuracy'],.91);self.assertEqual(done['documentation']['verification']['method'],'isolated worker')
    def test_research_experiment_blocks_unverified_execution(self):
        p=ResearchExperimentPipeline(Gen1(),lambda s:{'verification':{'verified':False}});r=p.run('r1',['m'],'h','method',approved=True);self.assertEqual(r['status'],'BLOCKED')
if __name__=='__main__':unittest.main()
