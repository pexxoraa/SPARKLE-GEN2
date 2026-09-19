import os,tempfile,unittest,uuid
from datetime import UTC,datetime,timedelta
from pathlib import Path
from unittest.mock import patch
from sparkle.contracts import ModelResponse,ToolCall
from sparkle.model import ModelAdapter
from sparkle.registry import ModelRegistry
from sparkle.system import SparkleSystem
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.delegation import DelegationRequest,SpecialistDelegationService
from sparkle_gen2.gen1 import LocalGen1Gateway,ToolObservation
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.storage import Gen2Store

PROJECT='packageapp';FILES={'src/main.py':'VALUE=7\n','config/app.json':'{"mode":"bounded"}\n'}

class PackageAdapter(ModelAdapter):
 provider='package-test';model_id='package-test'
 def __init__(self,args=None):self.calls=0;self.requests=[];self.args=args or {'project_name':PROJECT,'approved':True}
 def complete(self,request):
  self.calls+=1;self.requests.append(request)
  if self.calls==1:return ModelResponse('',self.model_id,self.provider,'tool_use',[ToolCall('pkg-1','workspace_package',dict(self.args))])
  return ModelResponse('The approved workspace package was created.',self.model_id,self.provider,'stop')
 def health(self):return {'configured':True}

class TamperArtifactGateway(LocalGen1Gateway):
 def __init__(self,s):super().__init__(s);self.tool_return=None
 def verify_delegated_action(self,tool,args,out):
  if tool=='workspace_package':
   self.tool_return=dict(out);root=self.system.artifacts.artifact_root.resolve();target=(root/str(out['artifact_name'])).resolve();target.write_bytes(target.read_bytes()+b'tamper')
  return super().verify_delegated_action(tool,args,out)

def gateway(adapter,cls=LocalGen1Gateway):
 r=ModelRegistry();r.inject(r.active_id,adapter);return cls(SparkleSystem(model_registry=r))
def plan(project=PROJECT,specialist='application_builder',extra=None):
 args={'project_name':project};args.update(extra or {})
 return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('delegate','Package exactly the approved workspace',['specialist_delegate'],[],['artifact digest and source relationship independently verified'],{'specialists':[specialist],'objective':'Package exactly the approved application workspace','authorized_action':{'tool':'workspace_package','arguments':args},'required_evidence':['artifact registry and digest reread']},30,0)],[{'description':'approved package independently verified','verification_method':'all_steps_verified'}],'MEDIUM',.95,[],'test-only')

def direct_plan():return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('calc','Calculate',['calculator'],[],['verified'],{'expression':'700+3'},30,0)],[{'description':'verified','verification_method':'all_steps_verified'}],'LOW',.9,[],'test')
class DirectGateway:
 def health(self):return {'available':True,'tools':['calculator'],'tool_definitions':[{'name':'calculator','parameters':{'type':'object'}}]}
 def retrieve_context(self,*a):return {'source':'test','rendered':'bounded'}
 def invoke(self,tool,args):return ToolObservation(True,tool,{'value':703},{'verified':True})

class Cycle50WorkspacePackageTests(unittest.TestCase):
 def _env(self,d):
  e=patch.dict(os.environ,{'SPARKLE_DATA_DIR':str(Path(d)/'gen1')});e.start();self.addCleanup(e.stop);Path(os.environ['SPARKLE_DATA_DIR']).mkdir(exist_ok=True)
 def _start(self,d,adapter=None,*,p=None,cls=LocalGen1Gateway,user='pkg-user'):
  self._env(d);a=adapter or PackageAdapter();g=gateway(a,cls);g.system.workspaces.scaffold(PROJECT,dict(FILES));db=Path(d)/'g2.db';agent=PersonalAgent(Gen2Store(db),g,planner=StaticPlanner(p or plan()),max_replans=0);first=agent.start('Package the approved workspace.',user_id=user);return db,g,a,agent,first
 def _approve(self,agent,first):
  self.assertEqual(first['status'],'WAITING');agent.decide_approval(first['approvals'][0],'approve',actor='human-reviewer');return agent.resume(first['goal_id'])

 def test_valid_package_exact_scope_artifact_and_provenance(self):
  with tempfile.TemporaryDirectory() as d:
   db,g,a,agent,first=self._start(d);self.assertEqual(a.calls,0);final=self._approve(agent,first);self.assertEqual(final['status'],'COMPLETED');rec=final['delegations'][0];grant=agent.delegation.grants.load(rec['request']['grant_id']);self.assertEqual(grant.scope['arguments'],{'project_name':PROJECT});self.assertEqual(grant.allowed_tools,['workspace_package']);self.assertEqual(grant.allowed_specialists,['application_builder']);self.assertEqual(grant.state,'CONSUMED')
   v=rec['result']['verification']['authorized_action_verification'][0]['verification'];self.assertTrue(v['verified']);artifact=g.artifact_content(v['artifact_id']);self.assertEqual(artifact['sha256'],v['artifact_sha256']);self.assertEqual(v['archive_format'],'zip-stored');self.assertEqual(v['project_name'],PROJECT)
   events=[e['event_type'] for e in Gen2Store(db).events(first['goal_id'])];self.assertIn('delegation_grant_consumed',events);self.assertIn('goal_completed',events);self.assertTrue(all(x.metadata.get('user_id')=='pkg-user' for x in a.requests))

 def test_no_approval_or_model_fake_approval_does_not_package(self):
  with tempfile.TemporaryDirectory() as d:
   _,g,a,_,first=self._start(d,PackageAdapter({'project_name':PROJECT,'approved':True,'approval_id':'fake'}));self.assertEqual(first['status'],'WAITING');self.assertEqual(a.calls,0);self.assertEqual(g.system.artifacts.list(limit=100),[])

 def test_scope_mutation_wrong_project_and_invented_output_fields_denied(self):
  for args in ({'project_name':'otherapp','approved':True},{'project_name':PROJECT,'output_path':'/tmp/x.zip','approved':True},{'project_name':PROJECT,'package_format':'tar','approved':True}):
   with self.subTest(args=args),tempfile.TemporaryDirectory() as d:
    _,g,_,agent,first=self._start(d,PackageAdapter(args));result=self._approve(agent,first);self.assertNotEqual(result['status'],'COMPLETED');self.assertEqual(g.system.artifacts.list(limit=100),[])

 def test_wrong_specialist_tool_capability_user_goal_denied(self):
  with tempfile.TemporaryDirectory() as d:
   _,_,_,agent,first=self._start(d);aid=first['approvals'][0];agent.decide_approval(aid,'approve',actor='human-reviewer');record=agent.delegation.load(first['delegations'][0]['request']['request_id']);grant=agent.delegation.grants.issue(record.request,agent.store.load_approval(aid));agent.delegation.attach_grant(record.request.request_id,grant.grant_id);req=agent.delegation.load(record.request.request_id).request
   cases=[(req,'research','workspace_package','workspace_package','specialist mismatch'),(req,'application_builder','workspace_test','workspace_package','tool mismatch'),(req,'application_builder','workspace_package','workspace_test','capability mismatch'),(DelegationRequest(**(req.to_dict()|{'user_id':'x'})),'application_builder','workspace_package','workspace_package','parent correlation'),(DelegationRequest(**(req.to_dict()|{'goal_id':'x'})),'application_builder','workspace_package','workspace_package','parent correlation')]
   for r,s,t,c,msg in cases:
    with self.subTest(msg=msg),self.assertRaisesRegex(PermissionError,msg):agent.delegation.grants.check(grant.grant_id,request=r,specialist=s,tool=t,capability=c,arguments={'project_name':PROJECT})

 def test_invalid_project_and_other_builder_specialists_rejected_before_approval(self):
  for p in (plan('../escape'),plan('/tmp/x'),plan('Bad Project'),plan(specialist='ai_builder'),plan(specialist='agent_builder')):
   with self.subTest(p=p),tempfile.TemporaryDirectory() as d:
    _,g,a,_,result=self._start(d,p=p);self.assertEqual(result['status'],'BLOCKED');self.assertEqual(result['approvals'],[]);self.assertEqual(a.calls,0);self.assertEqual(g.system.artifacts.list(limit=100),[])

 def test_source_workspace_change_after_approval_is_denied_before_grant_consumption(self):
  with tempfile.TemporaryDirectory() as d:
   _,g,_,agent,first=self._start(d);project=g.system.workspaces.root/PROJECT;(project/'src/main.py').write_text('VALUE=8\n',encoding='utf-8');agent.decide_approval(first['approvals'][0],'approve',actor='human-reviewer');result=agent.resume(first['goal_id']);self.assertNotEqual(result['status'],'COMPLETED');grant=agent.delegation.grants.for_request(first['delegations'][0]['request']['request_id']);self.assertEqual(grant.state,'ACTIVE');self.assertEqual(g.system.artifacts.list(limit=100),[])

 def test_execution_failure_no_false_completion(self):
  with tempfile.TemporaryDirectory() as d:
   _,g,_,agent,first=self._start(d);orig=g.system.artifacts.package;g.system.artifacts.package=lambda name:(_ for _ in ()).throw(RuntimeError('controlled package failure'))
   try:result=self._approve(agent,first)
   finally:g.system.artifacts.package=orig
   self.assertNotEqual(result['status'],'COMPLETED');grant=agent.delegation.grants.for_request(first['delegations'][0]['request']['request_id']);self.assertEqual((grant.state,grant.uses),('CONSUMED',1));self.assertEqual(g.system.artifacts.list(limit=100),[])

 def test_tool_success_but_artifact_digest_tamper_prevents_completion(self):
  with tempfile.TemporaryDirectory() as d:
   _,g,_,agent,first=self._start(d,cls=TamperArtifactGateway);result=self._approve(agent,first);self.assertEqual(g.tool_return['project_name'],PROJECT);self.assertNotEqual(result['status'],'COMPLETED');self.assertFalse(result['delegations'][0]['result']['verification']['verified']);self.assertIn('delegated_action_independent_verification_failed',str(result['delegations'][0]['result']['failure']))

 def test_restart_consumed_expired_and_idempotent_resume(self):
  with tempfile.TemporaryDirectory() as d:
   db,g,a,agent,first=self._start(d);aid=first['approvals'][0];agent.decide_approval(aid,'approve',actor='human-reviewer');r=agent.delegation.load(first['delegations'][0]['request']['request_id']);grant=agent.delegation.grants.issue(r.request,agent.store.load_approval(aid));agent.delegation.attach_grant(r.request.request_id,grant.grant_id);svc=SpecialistDelegationService(Gen2Store(db),g,PolicyEngine());req=svc.load(r.request.request_id).request;out=svc.execute(req);self.assertEqual(out.status,'COMPLETED');self.assertEqual(svc.grants.load(grant.grant_id).state,'CONSUMED');self.assertEqual(len(g.system.artifacts.list(limit=100)),1)
   with self.assertRaisesRegex(PermissionError,'not active'):SpecialistDelegationService(Gen2Store(db),g,PolicyEngine()).grants.check(grant.grant_id,request=req,specialist='application_builder',tool='workspace_package',capability='workspace_package',arguments={'project_name':PROJECT})
  with tempfile.TemporaryDirectory() as d:
   db,g,_,agent,first=self._start(d);aid=first['approvals'][0];agent.decide_approval(aid,'approve',actor='human-reviewer');r=agent.delegation.load(first['delegations'][0]['request']['request_id']);grant=agent.delegation.grants.issue(r.request,agent.store.load_approval(aid));agent.delegation.attach_grant(r.request.request_id,grant.grant_id);grant.expires_at=(datetime.now(UTC)-timedelta(seconds=1)).isoformat();grant.fingerprint=agent.delegation.grants.fingerprint(grant);agent.store.update_delegation_grant_payload(grant.grant_id,grant.to_dict());svc=SpecialistDelegationService(Gen2Store(db),g,PolicyEngine());req=svc.load(r.request.request_id).request
   with self.assertRaisesRegex(PermissionError,'expired'):svc.grants.check(grant.grant_id,request=req,specialist='application_builder',tool='workspace_package',capability='workspace_package',arguments={'project_name':PROJECT})
  with tempfile.TemporaryDirectory() as d:
   _,g,a,agent,first=self._start(d);done=self._approve(agent,first);count=len(g.system.artifacts.list(limit=100));calls=a.calls;again=agent.resume(first['goal_id']);self.assertEqual(again['status'],'COMPLETED');self.assertEqual(len(g.system.artifacts.list(limit=100)),count);self.assertEqual(a.calls,calls)

 def test_direct_package_and_calculator_regressions(self):
  with tempfile.TemporaryDirectory() as d:
   self._env(d);g=LocalGen1Gateway(SparkleSystem());g.system.workspaces.scaffold(PROJECT,dict(FILES));obs=g.invoke('workspace_package',{'project_name':PROJECT,'approved':True});self.assertTrue(obs.verification['verified']);self.assertIn('package digest',obs.verification['method'])
  with tempfile.TemporaryDirectory() as d:
   r=PersonalAgent(Gen2Store(Path(d)/'x.db'),DirectGateway(),planner=StaticPlanner(direct_plan())).start('Calculate 700+3');self.assertEqual(r['status'],'COMPLETED');self.assertEqual(r['delegations'],[])
if __name__=='__main__':unittest.main()
