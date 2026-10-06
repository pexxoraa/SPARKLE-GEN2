import tempfile,unittest,uuid
from pathlib import Path
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.core_time import now
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.storage import Gen2Store

class Gateway:
    def __init__(self):self.calls=[]
    def health(self):
        return {'available':True,'tools':['workspace_test'],'tool_definitions':[{'name':'workspace_test','description':'bounded','parameters':{'type':'object','properties':{'project_name':{'type':'string'}},'required':['project_name'],'additionalProperties':False}}]}
    def retrieve_context(self,*a,**k):return {'source':'test','rendered':''}
    def invoke(self,tool,args):
        self.calls.append((tool,dict(args)))
        ok=tool=='workspace_test' and set(args)=={'project_name','approved'} and args.get('approved') is True
        return ToolObservation(ok,tool,{'project_name':args.get('project_name'),'external_test_run_id':1},{'verified':ok,'isolation_verified':ok,'method':'test worker'})

def proposal(args):
    return PlanProposal(uuid.uuid4().hex,'workspace',[PlanProposalStep('test','Run isolated workspace tests',['workspace_test'],[],['signed worker result independently verified'],dict(args),30,0)],[{'description':'workspace tests verified','verification_method':'all_steps_verified'}],'MEDIUM',.99,[],now())

class WorkspaceTestApprovalIsolationTests(unittest.TestCase):
    def make(self,args):
        d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup);store=Gen2Store(Path(d.name)/'g.db');g=Gateway();a=PersonalAgent(store,g,planner=StaticPlanner(proposal(args)),max_replans=0);return store,g,a
    def test_model_cannot_self_approve_workspace_test(self):
        _,g,a=self.make({'project_name':'safeproj','approved':True});result=a.start('Test the approved workspace.',user_id='alice');self.assertEqual(result['status'],'BLOCKED');self.assertEqual(g.calls,[])
    def test_post_approval_workspace_mutation_is_rejected(self):
        store,g,a=self.make({'project_name':'safeproj'});first=a.start('Test the approved workspace.',user_id='alice');self.assertEqual(first['status'],'WAITING');plan=store.load_plan(store.load_goal(first['goal_id']).plan_id);plan.steps[0].arguments['project_name']='otherproj';store.save_plan(plan);a.decide_approval(first['approvals'][0],'approve',actor='human-reviewer');result=a.resume(first['goal_id']);self.assertEqual(result['status'],'BLOCKED');self.assertEqual(g.calls,[])
    def test_human_approval_creates_one_time_scope_and_injects_transport_flag(self):
        store,g,a=self.make({'project_name':'safeproj'});first=a.start('Test the approved workspace.',user_id='alice');self.assertEqual(first['status'],'WAITING');a.decide_approval(first['approvals'][0],'approve',actor='human-reviewer');done=a.resume(first['goal_id']);self.assertEqual(done['status'],'COMPLETED');self.assertEqual(g.calls,[('workspace_test',{'project_name':'safeproj','approved':True})]);permissions=[p for p in store.permissions_for_goal(first['goal_id']) if p.capability=='workspace_test' and p.metadata.get('one_time')];self.assertEqual(len(permissions),1);self.assertEqual(permissions[0].status.value,'REVOKED');events=[x['event_type'] for x in store.events(first['goal_id'])];self.assertIn('workspace_test_grant_issued',events);self.assertIn('workspace_test_grant_consumed',events)
    def test_model_visible_schema_hides_transport_approval_field(self):
        from sparkle.system import SparkleSystem
        from sparkle_gen2.gen1 import LocalGen1Gateway
        g=LocalGen1Gateway(SparkleSystem());d=next(x for x in g.health()['tool_definitions'] if x['name']=='workspace_test');self.assertEqual(set(d['parameters']['properties']),{'project_name'});self.assertEqual(d['parameters']['required'],['project_name'])

if __name__=='__main__':unittest.main()
