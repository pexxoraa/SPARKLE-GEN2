import tempfile,unittest
from pathlib import Path
from sparkle_gen2.proactive import ProactiveEventEngine
from sparkle_gen2.storage import Gen2Store

class Cycle19Tests(unittest.TestCase):
    def test_full_event_relevance_context_decision_policy_pipeline(self):
        with tempfile.TemporaryDirectory() as d:
            s=Gen2Store(Path(d)/'x.db')
            eng=ProactiveEventEngine(s,relevance_fn=lambda t,s,p:0.9,context_fn=lambda e:{'project':'alpha','permission':'ALLOW'},decision_fn=lambda e,c:{'action':'NOTIFY','rationale':'deadline near'},policy_fn=lambda e,a,c:{'allowed':c['permission']=='ALLOW','reason':'permission-aware'})
            e=eng.ingest('deadline_approaching','alpha',{'hours':2});out=eng.evaluate(e.event_id)
            self.assertEqual(out.status,'READY');self.assertEqual(out.action,'NOTIFY');self.assertEqual(out.context['project'],'alpha');self.assertTrue(out.policy['allowed'])
    def test_policy_can_block_relevant_event_without_action(self):
        with tempfile.TemporaryDirectory() as d:
            s=Gen2Store(Path(d)/'x.db');eng=ProactiveEventEngine(s,policy_fn=lambda e,a,c:{'allowed':False,'reason':'scope denied'})
            e=eng.ingest('important_email','mail',{},0.95);out=eng.evaluate(e.event_id)
            self.assertEqual(out.status,'BLOCKED');self.assertEqual(out.action,'NONE')
    def test_low_relevance_event_is_ignored_before_context_reasoning(self):
        with tempfile.TemporaryDirectory() as d:
            s=Gen2Store(Path(d)/'x.db');called=[];eng=ProactiveEventEngine(s,context_fn=lambda e:called.append(e.event_id) or {})
            e=eng.ingest('noise','x',{},0.1);out=eng.evaluate(e.event_id)
            self.assertEqual(out.status,'IGNORED');self.assertEqual(called,[])
if __name__=='__main__':unittest.main()
