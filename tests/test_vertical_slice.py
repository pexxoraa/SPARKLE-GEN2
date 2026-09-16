import tempfile,unittest
from pathlib import Path
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.storage import Gen2Store

class FakeGen1:
    def __init__(self,fail_once=False): self.state={"executions":0}; self.fail_once=fail_once
    def health(self): return {"available":True}
    def retrieve_context(self,request,requirements): return {"source":"fake-gen1","request":request}
    def invoke(self,tool,arguments):
        if self.fail_once:
            self.fail_once=False; return ToolObservation(False,tool,{"error":"induced"},{"verified":False})
        self.state["executions"]+=1; observed=self.state["executions"]
        return ToolObservation(True,tool,{"state":observed},{"verified":self.state["executions"]==observed,"method":"state-reread"})

class VerticalSliceTests(unittest.TestCase):
    def test_complete_vertical_slice(self):
        with tempfile.TemporaryDirectory() as d:
            gateway=FakeGen1(); store=Gen2Store(Path(d)/"g2.sqlite3"); result=PersonalAgent(store,gateway).start("Organize my Python learning for this week")
            self.assertEqual(result["status"],"COMPLETED"); self.assertEqual(gateway.state["executions"],1)
            self.assertEqual([e["event_type"] for e in store.events(result["goal_id"])],["goal_created","context_retrieved","plan_created","tool_observed","step_verified","goal_completed"])
    def test_failure_does_not_false_complete_and_can_retry(self):
        with tempfile.TemporaryDirectory() as d:
            gateway=FakeGen1(True); store=Gen2Store(Path(d)/"g2.sqlite3"); agent=PersonalAgent(store,gateway); first=agent.start("Do a bounded task")
            self.assertEqual(first["status"],"WAITING"); self.assertEqual(agent.resume(first["goal_id"])["status"],"COMPLETED")
    def test_restart_recovers_persisted_goal(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"g2.sqlite3"; gateway=FakeGen1(True); first=PersonalAgent(Gen2Store(path),gateway).start("Do a restart-safe task")
            self.assertEqual(first["status"],"WAITING"); self.assertEqual(PersonalAgent(Gen2Store(path),gateway).resume(first["goal_id"])["status"],"COMPLETED")
if __name__=="__main__": unittest.main()
