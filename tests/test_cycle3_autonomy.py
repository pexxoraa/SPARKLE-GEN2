import tempfile,unittest
from pathlib import Path
from sparkle_gen2.background import BackgroundTaskService
from sparkle_gen2.context_engine import ContextItem,PersonalContextEngine
from sparkle_gen2.proactive import ProactiveEventEngine
from sparkle_gen2.sessions import SessionService
from sparkle_gen2.storage import Gen2Store

class FakeAgent:
    def __init__(self,results):self.results=results;self.calls=0
    def resume(self,goal_id):
        value=self.results[min(self.calls,len(self.results)-1)];self.calls+=1;return value

class Cycle3AutonomyTests(unittest.TestCase):
    def test_context_is_minimal_relevant_permission_aware(self):
        engine=PersonalContextEngine(max_items=2,max_chars=100)
        sources={'memory':[ContextItem('memory','python','Python learning target',1,1),ContextItem('memory','secret','private token',1,1,'DENY')],
                 'project':[ContextItem('project','garden','unrelated garden task',1,.1)]}
        ctx=engine.build('plan Python learning',sources)
        self.assertEqual(ctx['items'][0]['key'],'python');self.assertFalse(any(i['key']=='secret' for i in ctx['items']));self.assertLessEqual(ctx['item_count'],2)
    def test_session_survives_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'g.sqlite3';s=SessionService(Gen2Store(path)).create('goal-1')
            recovered=SessionService(Gen2Store(path)).recover(s.session_id)
            self.assertEqual(recovered.active_goal_id,'goal-1');self.assertEqual(recovered.status,'ACTIVE')
    def test_background_pause_cancel_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'g.sqlite3';store=Gen2Store(path);agent=FakeAgent([{'status':'WAITING','approvals':[]}])
            svc=BackgroundTaskService(store,lambda:agent);t=svc.create('g1',3);self.assertEqual(t.state,'QUEUED')
            t=svc.resume(t.background_id);self.assertEqual(t.state,'WAITING');self.assertEqual(t.iterations,1)
            restarted=BackgroundTaskService(Gen2Store(path),lambda:agent);self.assertEqual(restarted.pause(t.background_id).state,'PAUSED')
            self.assertEqual(restarted.cancel(t.background_id).state,'CANCELLED');self.assertEqual(restarted.resume(t.background_id).state,'CANCELLED')
    def test_background_stops_for_approval_and_completes(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.sqlite3');agent=FakeAgent([{'status':'WAITING','approvals':['a1']}])
            svc=BackgroundTaskService(store,lambda:agent);t=svc.resume(svc.create('g1').background_id)
            self.assertEqual(t.state,'WAITING_FOR_APPROVAL')
            agent2=FakeAgent([{'status':'COMPLETED','approvals':[]}]);svc2=BackgroundTaskService(store,lambda:agent2)
            t.state='PAUSED';store.save_background_task(t);self.assertEqual(svc2.resume(t.background_id).state,'COMPLETED')
    def test_proactive_filters_noise_and_emits_action_summary(self):
        with tempfile.TemporaryDirectory() as d:
            engine=ProactiveEventEngine(Gen2Store(Path(d)/'g.sqlite3'),threshold=.7)
            low=engine.ingest('new_email','newsletter',{},.2);self.assertEqual(low.status,'IGNORED')
            high=engine.ingest('deadline_approaching','project alpha',{'hours':2},.9)
            result=engine.evaluate(high.event_id);self.assertEqual((result.status,result.action),('READY','NOTIFY'))

if __name__=='__main__':unittest.main()
