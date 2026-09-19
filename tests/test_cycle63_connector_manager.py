import json,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace

from sparkle.secrets import SecretResolver
from sparkle_gen2.connector_catalog import Gen1ToolConnector,build_default_connectors
from sparkle_gen2.connectors import (ConnectorAuthorizationMode,ConnectorAuthorizationState,ConnectorCapability,ConnectorDescriptor,ConnectorLifecycleState,ConnectorManager,ConnectorOperationMode)
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.core_time import now
from sparkle_gen2.dashboard import PersonalOperationsService
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.models import ApprovalStatus,PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.storage import Gen2Store

class Adapter:
    def __init__(self,*,healthy=True,verified=True,fail=None):self.healthy=healthy;self.verified=verified;self.fail=fail;self.calls=[]
    def health(self):return {'ok':self.healthy,'source':'test-adapter'}
    def invoke(self,operation,payload):
        self.calls.append((operation,dict(payload)))
        if self.fail=='timeout':raise TimeoutError('timeout')
        if self.fail:raise RuntimeError('provider failed')
        return {'operation':operation,'value':payload.get('value'),'external_request_id':'provider-ref'}
    def verify(self,operation,result):return {'verified':self.verified and result.get('operation')==operation,'method':'independent provider reread','external_request_id':result.get('external_request_id')}

class Gateway:
    def health(self):return {'tools':['file_read']}
    def invoke(self,tool,args):
        if tool!='file_read':return ToolObservation(False,tool,{'error':'denied'},{'verified':False})
        if set(args)!={'path'}:return ToolObservation(False,tool,{'error':'schema'},{'verified':False})
        return ToolObservation(True,tool,{'path':args['path'],'content':'actual local content'},{'verified':True,'method':'existing file boundary reread'})

class Cycle63ConnectorManagerTests(unittest.TestCase):
    def store(self,d):return Gen2Store(Path(d)/'g2.sqlite3')
    def descriptor(self,cid='svc',*,mode='READ',policy='connector_read',auth='NONE',secret_refs=(),external=None,device=False):
        cap=ConnectorCapability(f'{cid}.op','op',f'{cid}.op',ConnectorOperationMode(mode),policy)
        return ConnectorDescriptor(cid,cid.title(),cid,(cap,),ConnectorAuthorizationMode(auth),tuple(secret_refs),external,device,{})
    def manager(self,store=None,desc=None,adapter=None,secrets=None):
        m=ConnectorManager(store,policy=PolicyEngine(),secrets=secrets or SecretResolver({}));m.register_descriptor(desc or self.descriptor(),adapter=adapter)
        if adapter is not None:m.connect((desc or self.descriptor()).connector_id)
        return m
    def approved(self,goal='g',task='t',aid='a'):return SimpleNamespace(status=ApprovalStatus.APPROVED,goal_id=goal,task_run_id=task,approval_id=aid)

    def test_master_spec_connectors_registered_deterministically_and_external_not_live(self):
        m=build_default_connectors(secrets=SecretResolver({}));rows=m.discover();ids=[x['connector_id'] for x in rows];self.assertEqual(ids,sorted(ids));self.assertTrue({'gmail','outlook','calendar','drive','github','files','browser','linux','iot','ros2'}<=set(ids))
        for cid in ('gmail','outlook','calendar','drive','github','browser','linux','iot'):
            row=m.inspect(cid);self.assertFalse(row['healthy']);self.assertFalse(row['connected']);self.assertIn(m.health(cid)['status'],{'EXTERNALLY_BLOCKED','UNAVAILABLE'});self.assertNotEqual(row['status'],'LIVE_ACCEPTED')
        self.assertTrue(m.capabilities('gmail'));self.assertTrue(all({'capability','operation','scope','mode','policy_capability'}<=set(x) for x in m.capabilities('gmail')))

    def test_states_do_not_conflate_configuration_authorization_connection_health(self):
        d=self.descriptor('oauth',auth='OAUTH',secret_refs=('TOKEN',),external='oauth provider');a=Adapter();m=ConnectorManager(policy=PolicyEngine(),secrets=SecretResolver({'TOKEN':'configured-secret'}));m.register_descriptor(d,adapter=a);row=m.inspect('oauth');self.assertTrue(row['configured']);self.assertFalse(row['authorized']);self.assertFalse(row['connected']);self.assertFalse(row['healthy']);self.assertEqual(row['authorization_state'],'NOT_CONFIGURED')
        with self.assertRaises(PermissionError):m.connect('oauth')
        auth=m.authorize('oauth',['oauth.op'],actor='human',reference='oauth-record');self.assertEqual(auth['state'],'AUTHORIZED');h=m.connect('oauth');self.assertEqual(h['status'],'HEALTHY');row=m.inspect('oauth');self.assertTrue(row['configured']);self.assertTrue(row['authorized']);self.assertTrue(row['connected']);self.assertTrue(row['healthy'])

    def test_full_lifecycle_authorize_invoke_verify_revoke(self):
        d=self.descriptor('mail',mode='WRITE',policy='connector_write',auth='OAUTH',secret_refs=('TOKEN',),external='mail api');a=Adapter();m=ConnectorManager(policy=PolicyEngine(),secrets=SecretResolver({'TOKEN':'x'}));m.register_descriptor(d,adapter=a);m.authorize('mail',['mail.op'],owner_user_id='u',actor='human');m.connect('mail',owner_user_id='u');result=m.invoke('mail','op',{'value':1},owner_user_id='u',goal_id='g',task_run_id='t',trace_id='tr',approval=self.approved());self.assertEqual(result['status'],'VERIFIED');self.assertTrue(result['verification']['verified']);rv=m.revoke('mail',owner_user_id='u',actor='human');self.assertEqual(rv['previous_state'],'HEALTHY');self.assertEqual(m.health('mail',owner_user_id='u')['status'],'REVOKED');
        with self.assertRaises(PermissionError):m.invoke('mail','op',{'value':2},owner_user_id='u',goal_id='g',task_run_id='t',approval=self.approved())

    def test_authorization_pending_expired_revoked_and_invalid_transitions(self):
        d=self.descriptor('svc',auth='OAUTH',secret_refs=('TOKEN',),external='provider');m=ConnectorManager(policy=PolicyEngine(),secrets=SecretResolver({'TOKEN':'x'}));m.register_descriptor(d,adapter=Adapter());m.set_authorization_state('svc','PENDING');self.assertEqual(m.inspect('svc')['authorization_state'],'PENDING');m.authorize('svc',['svc.op']);m.set_authorization_state('svc','EXPIRED');self.assertEqual(m.inspect('svc')['authorization_state'],'EXPIRED')
        with self.assertRaises(PermissionError):m.connect('svc')
        m.set_authorization_state('svc','REVOKED');self.assertEqual(m.health('svc')['status'],'REVOKED')
        with self.assertRaises(PermissionError):m.connect('svc')
        with self.assertRaises(ValueError):m.set_authorization_state('svc','AUTHORIZED')

    def test_policy_allow_require_approval_and_deny(self):
        read=self.descriptor('read',policy='connector_read');a=Adapter();m=self.manager(desc=read,adapter=a);r=m.invoke('read','op',{'value':1},goal_id='g',task_run_id='t');self.assertEqual(r['status'],'VERIFIED')
        write=self.descriptor('write',mode='WRITE',policy='connector_write');b=Adapter();m2=self.manager(desc=write,adapter=b)
        with self.assertRaises(PermissionError):m2.invoke('write','op',{'value':1},goal_id='g',task_run_id='t')
        self.assertEqual(m2.invoke('write','op',{'value':1},goal_id='g',task_run_id='t',approval=self.approved())['status'],'VERIFIED')
        denied=self.descriptor('denied',policy='not_registered');m3=self.manager(desc=denied,adapter=Adapter())
        with self.assertRaises(PermissionError):m3.invoke('denied','op',{},goal_id='g',task_run_id='t')

    def test_model_authority_fields_never_authorize(self):
        m=self.manager(adapter=Adapter())
        for key in ('approved','approval_id','grant_id','authorization_override'):
            with self.subTest(key=key),self.assertRaises(PermissionError):m.invoke('svc','op',{key:True})

    def test_request_identity_owner_goal_task_trace_and_provenance_persist(self):
        with tempfile.TemporaryDirectory() as d:
            store=self.store(d);m=self.manager(store,adapter=Adapter());r=m.invoke('svc','op',{'value':7},owner_user_id='alice',goal_id='g',task_run_id='t',trace_id='tr');rows=store.connector_invocations(owner_user_id='alice');self.assertEqual(len(rows),1);x=rows[0];self.assertEqual((x['request_id'],x['connector_id'],x['owner_user_id'],x['goal_id'],x['task_run_id'],x['trace_id']),(r['request_id'],'svc','alice','g','t','tr'));self.assertEqual(x['verification_status'],'VERIFIED');self.assertEqual(x['provenance']['provider_system'],'svc');self.assertNotIn('value',x['result_summary'])

    def test_provider_failure_timeout_and_verification_failure_never_succeed(self):
        for fail in ('provider','timeout'):
            m=self.manager(adapter=Adapter(fail=fail))
            with self.subTest(fail=fail),self.assertRaises((RuntimeError,TimeoutError)):m.invoke('svc','op',{})
            self.assertEqual(m.invocations()[0]['status'],'FAILED')
        m=self.manager(adapter=Adapter(verified=False));r=m.invoke('svc','op',{});self.assertEqual(r['status'],'FAILED');self.assertFalse(r['verification']['verified']);self.assertEqual(m.invocations()[0]['verification_status'],'FAILED')

    def test_secret_values_never_persist_and_protected_external_content_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            store=self.store(d);desc=self.descriptor('ext',auth='OAUTH',secret_refs=('TOKEN',),external='external api');a=Adapter();m=ConnectorManager(store,policy=PolicyEngine(),secrets=SecretResolver({'TOKEN':'super-secret-token-value'}));m.register_descriptor(desc,adapter=a);m.authorize('ext',['ext.op'],owner_user_id='u',actor='human');m.connect('ext',owner_user_id='u');m.invoke('ext','op',{'value':'ordinary'},owner_user_id='u');raw=Path(store.path).read_bytes();self.assertNotIn(b'super-secret-token-value',raw)
            for c in ('SENSITIVE','HIGHLY_SENSITIVE','DEVICE_CONTROL'):
                with self.subTest(c=c),self.assertRaises(PermissionError):m.invoke('ext','op',{'value':'protected'},owner_user_id='u',classification=c)
            self.assertEqual(len(a.calls),1)

    def test_owner_and_device_isolation(self):
        with tempfile.TemporaryDirectory() as d:
            store=self.store(d);m=self.manager(store,adapter=Adapter());m.invoke('svc','op',{},owner_user_id='alice');self.assertEqual(len(m.invocations(owner_user_id='alice')),1);self.assertEqual(m.invocations(owner_user_id='bob'),[])
            desc=self.descriptor('device',device=True);a=Adapter();m.register_descriptor(desc,adapter=a);m.connect('device')
            with self.assertRaises(PermissionError):m.invoke('device','op',{})
            self.assertEqual(m.invoke('device','op',{},device_id='dev-1')['status'],'VERIFIED')

    def test_restart_recovers_persisted_state_but_revalidates_health(self):
        with tempfile.TemporaryDirectory() as d:
            store=self.store(d);desc=self.descriptor('svc');a=Adapter();m=ConnectorManager(store,policy=PolicyEngine());m.register_descriptor(desc,adapter=a);m.connect('svc');m.invoke('svc','op',{'value':1},owner_user_id='alice');self.assertEqual(m.health('svc')['status'],'HEALTHY')
            m2=ConnectorManager(Gen2Store(Path(d)/'g2.sqlite3'),policy=PolicyEngine());m2.register_descriptor(desc,adapter=a);self.assertEqual(m2.health('svc')['status'],'HEALTHY');self.assertEqual(len(m2.invocations(owner_user_id='alice')),1)
            ext=self.descriptor('ext',auth='OAUTH',secret_refs=('TOKEN',),external='provider');m3=ConnectorManager(store,policy=PolicyEngine(),secrets=SecretResolver({'TOKEN':'x'}));m3.register_descriptor(ext,adapter=Adapter());m3.authorize('ext',['ext.op']);m3.connect('ext');self.assertEqual(m3.health('ext')['status'],'HEALTHY')
            m4=ConnectorManager(Gen2Store(Path(d)/'g2.sqlite3'),policy=PolicyEngine(),secrets=SecretResolver({'TOKEN':'x'}));m4.register_descriptor(ext);self.assertEqual(m4.health('ext')['status'],'EXTERNALLY_BLOCKED');self.assertFalse(m4.inspect('ext')['connected'])

    def test_files_adapter_wraps_existing_gateway_and_preserves_verification(self):
        m=build_default_connectors(policy=PolicyEngine(),gateway=Gateway(),secrets=SecretResolver({}));self.assertEqual(m.health('files')['status'],'HEALTHY');r=m.invoke('files','read',{'path':'README.md'},'files.read',owner_user_id='u',goal_id='g',task_run_id='t');self.assertEqual(r['result']['tool'],'file_read');self.assertTrue(r['verification']['verified']);self.assertEqual(r['result']['output']['content'],'actual local content')
        with self.assertRaises((KeyError,PermissionError)):m.invoke('files','write',{'path':'x'},'files.write',owner_user_id='u',goal_id='g',task_run_id='t',approval=self.approved())

    def test_personalagent_connector_read_inspection(self):
        with tempfile.TemporaryDirectory() as d:
            store=self.store(d);m=self.manager(store,adapter=Adapter());proposal=PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('s','Inspect connector',['connector_inspect'],[],['state reread'],{'connector_id':'svc'},30,0)],[{'description':'connector inspected','verification_method':'all_steps_verified'}],'LOW',.9,[],now());agent=PersonalAgent(store,SimpleNamespace(**{}),planner=StaticPlanner(proposal),connector_manager=m)
            # Minimal Gen1 gateway behavior used by PersonalAgent planning/context/execution health.
            agent.gen1=SimpleNamespace(health=lambda:{'tools':[],'tool_definitions':[]},retrieve_context=lambda *a,**k:{'source':'test','rendered':''},invoke=lambda *a,**k:ToolObservation(False,'x',{},{}));result=agent.start('Inspect connector.',user_id='alice');self.assertEqual(result['status'],'COMPLETED');self.assertIn('Connector svc',result['text'])

    def test_personalagent_connector_write_requires_trusted_approval_and_scope(self):
        with tempfile.TemporaryDirectory() as d:
            store=self.store(d);desc=self.descriptor('writer',mode='WRITE',policy='connector_write');a=Adapter();m=self.manager(store,desc,a);proposal=PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('s','Write through connector',['connector_invoke'],[],['verified effect'],{'connector_id':'writer','operation':'op','arguments':{'value':1},'classification':'PRIVATE'},30,0)],[{'description':'write verified','verification_method':'all_steps_verified'}],'MEDIUM',.9,[],now());g=SimpleNamespace(health=lambda:{'tools':[],'tool_definitions':[]},retrieve_context=lambda *a,**k:{'source':'test','rendered':''},invoke=lambda *a,**k:ToolObservation(False,'x',{},{}));agent=PersonalAgent(store,g,planner=StaticPlanner(proposal),connector_manager=m);first=agent.start('Do connector write.',user_id='user');self.assertEqual(first['status'],'WAITING');self.assertEqual(a.calls,[]);agent.decide_approval(first['approvals'][0],'approve',actor='human');done=agent.resume(first['goal_id']);self.assertEqual(done['status'],'COMPLETED');self.assertEqual(len(a.calls),1)

    def test_personalagent_model_cannot_self_approve_connector_action(self):
        with tempfile.TemporaryDirectory() as d:
            store=self.store(d);desc=self.descriptor('writer',mode='WRITE',policy='connector_write');a=Adapter();m=self.manager(store,desc,a);proposal=PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('s','Write',['connector_invoke'],[],['verified'],{'connector_id':'writer','operation':'op','arguments':{'value':1},'approved':True},30,0)],[{'description':'v','verification_method':'all_steps_verified'}],'MEDIUM',.9,[],now());g=SimpleNamespace(health=lambda:{'tools':[],'tool_definitions':[]},retrieve_context=lambda *a,**k:{'source':'test','rendered':''},invoke=lambda *a,**k:ToolObservation(False,'x',{},{}));agent=PersonalAgent(store,g,planner=StaticPlanner(proposal),connector_manager=m);r=agent.start('x');self.assertEqual(r['status'],'BLOCKED');self.assertEqual(a.calls,[])

    def test_operations_snapshot_exposes_connector_counts_auth_required_and_failures(self):
        with tempfile.TemporaryDirectory() as d:
            store=self.store(d);m=build_default_connectors(store=store,policy=PolicyEngine(),gateway=Gateway(),secrets=SecretResolver({}));snap=PersonalOperationsService(store,connectors=m).snapshot(owner_user_id='user');c=snap['intelligence']['connectors'];self.assertGreaterEqual(c['counts']['total'],10);self.assertGreaterEqual(c['counts']['healthy'],1);self.assertGreater(c['counts']['blocked'],0);self.assertGreater(c['counts']['authorization_required'],0);self.assertTrue(any(x['connector_id']=='gmail' for x in c['recent_failures']))

    def test_state_changing_invocation_is_idempotent_by_stable_request_identity(self):
        desc=self.descriptor('write',mode='WRITE',policy='connector_write');a=Adapter();m=self.manager(desc=desc,adapter=a);approval=self.approved();one=m.invoke('write','op',{'value':1},goal_id='g',task_run_id='t',trace_id='tr',approval=approval);two=m.invoke('write','op',{'value':1},goal_id='g',task_run_id='t',trace_id='tr',approval=approval);self.assertEqual(one['request_id'],two['request_id']);self.assertTrue(two['reused']);self.assertEqual(len(a.calls),1)

    def test_personalagent_approved_connector_scope_mutation_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            store=self.store(d);desc=self.descriptor('writer',mode='WRITE',policy='connector_write');a=Adapter();m=self.manager(store,desc,a);proposal=PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('s','Write through connector',['connector_invoke'],[],['verified effect'],{'connector_id':'writer','operation':'op','arguments':{'value':1},'classification':'PRIVATE'},30,0)],[{'description':'write verified','verification_method':'all_steps_verified'}],'MEDIUM',.9,[],now());g=SimpleNamespace(health=lambda:{'tools':[],'tool_definitions':[]},retrieve_context=lambda *a,**k:{'source':'test','rendered':''},invoke=lambda *a,**k:ToolObservation(False,'x',{},{}));agent=PersonalAgent(store,g,planner=StaticPlanner(proposal),connector_manager=m);first=agent.start('Do connector write.',user_id='user');agent.decide_approval(first['approvals'][0],'approve',actor='human');plan=store.load_plan(store.load_goal(first['goal_id']).plan_id);plan.steps[0].arguments['arguments']['value']=2;store.save_plan(plan);done=agent.resume(first['goal_id']);self.assertEqual(done['status'],'BLOCKED');self.assertEqual(a.calls,[])

if __name__=='__main__':unittest.main()
