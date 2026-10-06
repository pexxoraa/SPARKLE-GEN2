import tempfile,unittest,uuid
from pathlib import Path
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.core_time import now
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.learning_orchestration import LearningOrchestrator
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.storage import Gen2Store

class Gateway:
    def health(self):return {'available':True,'tools':['learning_progress'],'tool_definitions':[]}
    def retrieve_context(self,*a,**k):return {'source':'test','rendered':''}
    def invoke(self,tool,args):
        if tool=='learning_progress':return ToolObservation(True,tool,{'course':args['course'],'completed':1,'total':3},{'verified':True,'method':'verified learning store reread'})
        return ToolObservation(False,tool,{}, {'verified':False})

def proposal(tool,args):
    return PlanProposal(uuid.uuid4().hex,'learning',[PlanProposalStep('learn','Manage adaptive learning',[tool],[],['persisted learning state reread'],args,30,0)],[{'description':'learning state verified','verification_method':'all_steps_verified'}],'MEDIUM' if tool!='learning_plan_inspect' else 'LOW',.98,[],'test-only')

class MasterLearningTests(unittest.TestCase):
    def service(self,d,gateway=None):
        store=Gen2Store(Path(d)/'g.db');g=gateway or Gateway();return store,g,LearningOrchestrator(store,g)
    def test_create_persists_bounded_curriculum_and_verified_progress_digest(self):
        with tempfile.TemporaryDirectory() as d:
            store,g,svc=self.service(d);p=svc.create(owner_user_id='alice',subject='Python',objective='Build reliable Python skills',units=['Syntax','Testing','Debugging']);self.assertEqual(p.status,'ACTIVE');self.assertEqual(len(p.units),3);self.assertEqual(p.source_progress['status'],'VERIFIED');self.assertIn('output_sha256',p.source_progress);self.assertEqual(set(p.source_progress),{'status','tool','verification_method','output_sha256','fields'});self.assertEqual(p.source_progress['fields'],['completed','course','total']);r=LearningOrchestrator(Gen2Store(Path(d)/'g.db'),g).get(p.plan_id,owner_user_id='alice');self.assertEqual(r.provenance['curriculum_digest'],p.provenance['curriculum_digest'])
    def test_duplicate_creation_is_idempotent_and_owner_isolated(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,svc=self.service(d);a=svc.create(owner_user_id='alice',subject='Python',objective='Learn',units=['A','B']);b=svc.create(owner_user_id='alice',subject='Python',objective='Learn',units=['A','B']);self.assertEqual(a.plan_id,b.plan_id);self.assertEqual(len(svc.list(owner_user_id='alice')),1);self.assertEqual(svc.list(owner_user_id='bob'),[]);self.assertRaises(PermissionError,svc.get,a.plan_id,owner_user_id='bob')
    def test_assessment_computes_weakness_retraining_and_completion_deterministically(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,svc=self.service(d);p=svc.create(owner_user_id='u',subject='Robotics',objective='Master safety',units=['Kinematics','Safety']);u1,u2=[x['unit_id'] for x in p.units];one=svc.assess(p.plan_id,owner_user_id='u',unit_id=u1,score=.4,evidence_reference='assessment:quiz-1');self.assertIn(u1,one['plan'].weaknesses);two=svc.assess(p.plan_id,owner_user_id='u',unit_id=u1,score=.5,evidence_reference='assessment:quiz-2');self.assertEqual(two['plan'].status,'NEEDS_RETRAINING');self.assertEqual(two['plan'].retraining[0]['unit_id'],u1);svc.assess(p.plan_id,owner_user_id='u',unit_id=u1,score=.9,evidence_reference='assessment:quiz-3');done=svc.assess(p.plan_id,owner_user_id='u',unit_id=u2,score=.95,evidence_reference='assessment:quiz-4');self.assertEqual(done['plan'].status,'COMPLETED');self.assertEqual(done['plan'].weaknesses,[])
    def test_assessment_idempotency_invalid_input_and_secret_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,svc=self.service(d);p=svc.create(owner_user_id='u',subject='X',objective='Y',units=['Unit']);uid=p.units[0]['unit_id'];a=svc.assess(p.plan_id,owner_user_id='u',unit_id=uid,score=.8,evidence_reference='assessment:one');b=svc.assess(p.plan_id,owner_user_id='u',unit_id=uid,score=.8,evidence_reference='assessment:one');self.assertTrue(b['reused']);self.assertEqual(len(b['plan'].assessments),1)
            with self.assertRaises(ValueError):svc.assess(p.plan_id,owner_user_id='u',unit_id=uid,score=2,evidence_reference='bad')
            with self.assertRaises(ValueError):svc.create(owner_user_id='u',subject='X',objective='api_key=secret',units=['A'])
            with self.assertRaises(ValueError):svc.create(owner_user_id='u',subject='X',objective='Y',units=['A','a'])
    def test_missing_gen1_progress_is_honest_not_fabricated(self):
        class G(Gateway):
            def invoke(self,t,a):return ToolObservation(False,t,{'error':'none'},{'verified':False})
        with tempfile.TemporaryDirectory() as d:
            _,_,svc=self.service(d,G());p=svc.create(owner_user_id='u',subject='New skill',objective='Learn it',units=['Intro']);self.assertEqual(p.source_progress['status'],'UNAVAILABLE');self.assertEqual(p.units[0]['status'],'PENDING')
    def test_policy_requires_approval_for_mutations_but_inspection_is_readonly(self):
        policy=PolicyEngine();self.assertEqual(policy.evaluate('learning_plan_create','u','s',now())[0].effect.value,'REQUIRE_APPROVAL');self.assertEqual(policy.evaluate('learning_assess','u','s',now())[0].effect.value,'REQUIRE_APPROVAL');self.assertEqual(policy.evaluate('learning_plan_inspect','u','s',now())[0].effect.value,'ALLOW')
    def test_personalagent_plan_creation_requires_exact_human_approval(self):
        with tempfile.TemporaryDirectory() as d:
            store,g,svc=self.service(d);args={'subject':'Python','objective':'Improve Python','units':['Syntax','Testing']};agent=PersonalAgent(store,g,planner=StaticPlanner(proposal('learning_plan_create',args)),learning_service=svc);first=agent.start('Build my Python learning plan.',user_id='alice');self.assertEqual(first['status'],'WAITING');self.assertEqual(svc.list(owner_user_id='alice'),[]);plan=store.load_plan(store.load_goal(first['goal_id']).plan_id);plan.steps[0].arguments['objective']='Mutated objective';store.save_plan(plan);agent.decide_approval(first['approvals'][0],'approve',actor='human');blocked=agent.resume(first['goal_id']);self.assertEqual(blocked['status'],'BLOCKED');self.assertEqual(svc.list(owner_user_id='alice'),[])
    def test_personalagent_approved_create_and_assessment_are_verified(self):
        with tempfile.TemporaryDirectory() as d:
            store,g,svc=self.service(d);create=PersonalAgent(store,g,planner=StaticPlanner(proposal('learning_plan_create',{'subject':'Robotics','objective':'Improve robotics','units':['Safety']})),learning_service=svc);first=create.start('Create the plan',user_id='u');create.decide_approval(first['approvals'][0],'approve',actor='human');done=create.resume(first['goal_id']);self.assertEqual(done['status'],'COMPLETED');p=svc.list(owner_user_id='u')[0];uid=p.units[0]['unit_id'];assess=PersonalAgent(store,g,planner=StaticPlanner(proposal('learning_assess',{'plan_id':p.plan_id,'unit_id':uid,'score':.9,'evidence_reference':'assessment:approved'})),learning_service=svc);pending=assess.start('Record my approved assessment',user_id='u');self.assertEqual(pending['status'],'WAITING');assess.decide_approval(pending['approvals'][0],'approve',actor='human');result=assess.resume(pending['goal_id']);self.assertEqual(result['status'],'COMPLETED');self.assertEqual(svc.get(p.plan_id,owner_user_id='u').status,'COMPLETED');self.assertTrue(any(e['event_type']=='learning_state_updated' for e in store.events(result['goal_id'])))
    def test_restart_preserves_retraining_and_no_hidden_model_state(self):
        with tempfile.TemporaryDirectory() as d:
            store,g,svc=self.service(d);p=svc.create(owner_user_id='u',subject='Robotics',objective='Practice',units=['Safety']);uid=p.units[0]['unit_id'];svc.assess(p.plan_id,owner_user_id='u',unit_id=uid,score=.2,evidence_reference='assessment:a');svc.assess(p.plan_id,owner_user_id='u',unit_id=uid,score=.3,evidence_reference='assessment:b');raw=Path(store.path).read_text(errors='ignore');self.assertNotIn('chain_of_thought',raw);restarted=LearningOrchestrator(Gen2Store(Path(d)/'g.db'),g).get(p.plan_id,owner_user_id='u');self.assertEqual(restarted.status,'NEEDS_RETRAINING');self.assertEqual(len(restarted.retraining),1)
if __name__=='__main__':unittest.main()
