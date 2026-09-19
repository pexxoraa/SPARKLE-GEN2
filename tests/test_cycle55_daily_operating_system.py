import tempfile,unittest,uuid
from pathlib import Path
from sparkle_gen2.daily_os import DailyOperatingSystemService
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.models import PlanProposal,PlanProposalStep,ModelProvenance
from sparkle_gen2.planner import StaticPlanner

class Context:
    def __init__(self,items=None):self.items=items or []
    def gather(self,goal):return {'goal':goal,'items':self.items,'item_count':len(self.items),'char_count':sum(len(str(x.get('value',''))) for x in self.items)}
class G:
    def health(self):return {'available':True,'tools':[],'tool_definitions':[]}
    def retrieve_context(self,*a):return {'source':'test','rendered':''}
    def invoke(self,*a):raise AssertionError('unexpected lower invocation')
def item(source,key,value,score=.9,prov=None):return {'source':source,'key':key,'value':value,'score':score,'provenance':prov or {'origin':source}}
def plan(tool,args):return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('d','Daily OS operation',[tool],[],['daily state reread'],args,30,0)],[{'description':'daily state verified','verification_method':'all_steps_verified'}],'LOW',.99,[],'test')

class DailyOSTests(unittest.TestCase):
    def test_internal_lifecycle_events_are_not_promoted_to_daily_priorities(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.db');ctx=Context([item('recent_activity','goal_created','internal'),item('recent_activity','deadline_approaching','deadline today'),item('recent_activity','tool_observed','internal')]);b=DailyOperatingSystemService(store,ctx).generate(user_id='u',day='2026-09-19');self.assertEqual([x['key'] for x in b.items],['deadline_approaching'])

    def test_generate_persists_ranked_provenance_and_idempotency(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.db');ctx=Context([item('calendar','meeting','deadline today robotics review',.9,{'connector':'calendar'}),item('memory','pref','concise updates',.6)]);svc=DailyOperatingSystemService(store,ctx);a=svc.generate(user_id='u',day='2026-09-19');b=svc.generate(user_id='u',day='2026-09-19');self.assertEqual(a.brief_id,b.brief_id);self.assertEqual(len(store.daily_briefs(owner_user_id='u')),1);self.assertEqual(a.items[0]['source'],'calendar');self.assertEqual(a.items[0]['provenance']['connector'],'calendar');self.assertEqual(a.status,'READY')
    def test_unavailable_context_and_invalid_input_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            svc=DailyOperatingSystemService(Gen2Store(Path(d)/'g2.db'),None)
            with self.assertRaisesRegex(RuntimeError,'daily_context_unavailable'):svc.generate(user_id='u')
        with tempfile.TemporaryDirectory() as d:
            svc=DailyOperatingSystemService(Gen2Store(Path(d)/'g2.db'),Context())
            with self.assertRaises(ValueError):svc.generate(user_id='u',day='today')
    def test_owner_scope_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'g2.db';svc=DailyOperatingSystemService(Gen2Store(db),Context([item('tasks','t1','today task')])) ;b=svc.generate(user_id='alice',day='2026-09-19');
            with self.assertRaises(PermissionError):svc.inspect(user_id='bob',brief_id=b.brief_id)
            restarted=DailyOperatingSystemService(Gen2Store(db),Context());self.assertEqual(restarted.inspect(user_id='alice',brief_id=b.brief_id).brief_id,b.brief_id)
    def test_unresolved_items_carry_forward_but_done_items_do_not(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.db');svc=DailyOperatingSystemService(store,Context([item('tasks','a','overdue task'),item('projects','b','project work')]));first=svc.generate(user_id='u',day='2026-09-18');svc.update_item(user_id='u',brief_id=first.brief_id,item_id=first.items[0]['item_id'],state='DONE');svc.context_provider=Context([]);second=svc.generate(user_id='u',day='2026-09-19');self.assertEqual(second.carry_count,1);self.assertTrue(all(x['state']=='OPEN' for x in second.items));self.assertNotIn(first.items[0]['item_id'],[x['item_id'] for x in second.items]);self.assertEqual(second.items[0]['carried_from'],first.brief_id)
    def test_personal_agent_generate_is_readonly_grounded_and_traced(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.db');ctx=Context([item('tasks','robotics','deadline today calibrate robot')]);svc=DailyOperatingSystemService(store,ctx);agent=PersonalAgent(store,G(),planner=StaticPlanner(plan('daily_brief_generate',{'day':'2026-09-19'})),daily_os_service=svc);r=agent.start('What should I focus on today?',user_id='alice');self.assertEqual(r['status'],'COMPLETED');self.assertEqual(r['approvals'],[]);self.assertIn('Daily brief 2026-09-19',r['text']);self.assertTrue(any(x['kind']=='action' and x['component']=='daily_brief_generate' for x in store.operation_traces(trace_id=r['trace_id'])))
    def test_update_requires_human_approval_exact_scope_and_reread(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.db');svc=DailyOperatingSystemService(store,Context([item('tasks','t','today task')]));b=svc.generate(user_id='alice',day='2026-09-19');iid=b.items[0]['item_id'];agent=PersonalAgent(store,G(),planner=StaticPlanner(plan('daily_brief_update',{'brief_id':b.brief_id,'item_id':iid,'state':'DONE'})),daily_os_service=svc);first=agent.start('Mark that daily item done.',user_id='alice');self.assertEqual(first['status'],'WAITING');self.assertEqual(svc.inspect(user_id='alice',brief_id=b.brief_id).items[0]['state'],'OPEN');aid=first['approvals'][0];approval=store.load_approval(aid);self.assertIn(iid,approval.requested_scope);agent.decide_approval(aid,'approve',actor='human-reviewer');done=agent.resume(first['goal_id']);self.assertEqual(done['status'],'COMPLETED');self.assertEqual(svc.inspect(user_id='alice',brief_id=b.brief_id).items[0]['state'],'DONE')
    def test_approved_scope_mutation_is_denied(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.db');svc=DailyOperatingSystemService(store,Context([item('tasks','t','today task')]));b=svc.generate(user_id='alice',day='2026-09-19');iid=b.items[0]['item_id'];agent=PersonalAgent(store,G(),planner=StaticPlanner(plan('daily_brief_update',{'brief_id':b.brief_id,'item_id':iid,'state':'DONE'})),daily_os_service=svc);first=agent.start('Update daily item.',user_id='alice');aid=first['approvals'][0];p=store.load_plan(store.load_goal(first['goal_id']).plan_id);p.steps[0].arguments['state']='DISMISSED';store.save_plan(p);agent.decide_approval(aid,'approve',actor='human-reviewer');result=agent.resume(first['goal_id']);self.assertEqual(result['status'],'BLOCKED');self.assertEqual(svc.inspect(user_id='alice',brief_id=b.brief_id).items[0]['state'],'OPEN')
    def test_model_supplied_approval_field_cannot_authorize_update(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.db');svc=DailyOperatingSystemService(store,Context([item('tasks','t','today task')]));b=svc.generate(user_id='u',day='2026-09-19');iid=b.items[0]['item_id'];agent=PersonalAgent(store,G(),planner=StaticPlanner(plan('daily_brief_update',{'brief_id':b.brief_id,'item_id':iid,'state':'DONE','approved':True})),daily_os_service=svc);r=agent.start('Update.',user_id='u');self.assertEqual(r['status'],'BLOCKED');self.assertEqual(svc.inspect(user_id='u',brief_id=b.brief_id).items[0]['state'],'OPEN')
if __name__=='__main__':unittest.main()
