from pathlib import Path
import json,tempfile,unittest
from sparkle_gen2.gen1 import LocalGen1Gateway
from sparkle_gen2.retrieval import DeterministicRetrievalRuntime

class Cycle44Tests(unittest.TestCase):
 def test_packaged_registry_contains_exactly_one_nemotron(self):
  p=Path(__file__).parents[1]/"src/sparkle_gen2/nemotron_models.json";d=json.loads(p.read_text())
  self.assertEqual(len(d["models"]),1);m=d["models"][0];self.assertEqual(m["provider"],"nvidia");self.assertIn("nemotron",m["model_id"].lower());self.assertFalse(m["allow_fallback"])
 def test_repository_has_no_retired_local_ai_runtime_names(self):
  root=Path(__file__).parents[1];banned=["q"+"wen","no"+"mic-embed","moon"+"dream","ol"+"lama"]
  hits=[]
  for base in (root/"src",root/"tests",root/"docs",root/"README.md"):
   files=[base] if base.is_file() else list(base.rglob("*"))
   for p in files:
    if p.is_file() and "__pycache__" not in p.parts:
     try:text=p.read_text(errors="ignore").lower()
     except Exception:continue
     for term in banned:
      if term in text:hits.append((str(p.relative_to(root)),term))
  self.assertEqual(hits,[])
 def test_deterministic_bm25_retrieval_is_model_free(self):
  r=DeterministicRetrievalRuntime();docs=[{"id":"b","text":"gardening notes"},{"id":"a","text":"visual slam robotics localization","metadata":{"project":"robotics"}}]
  self.assertEqual(r.retrieve("robotics slam",docs,k=1)[0]["id"],"a")
 def test_non_nemotron_router_decision_is_rejected(self):
  from types import SimpleNamespace
  class Router:
   def complete(self,*a,**k):
    return SimpleNamespace(provider="other",model="other/model",capability="reasoning",selection_reason="x",health="HEALTHY",fallback=False),SimpleNamespace(text="{}",provider_request_id="r")
  g=LocalGen1Gateway.__new__(LocalGen1Gateway);g.system=SimpleNamespace(model_router=Router())
  goal={"goal_id":"g","user_request":"x","constraints":[],"deadline":None}
  with self.assertRaisesRegex(RuntimeError,"nemotron_only_route_violation"):g.plan(goal,{"rendered":""},["calculator"])
 def test_planning_failure_executes_zero_tools(self):
  from types import SimpleNamespace
  from sparkle_gen2.core import PersonalAgent
  from sparkle_gen2.storage import Gen2Store
  class G:
   invoked=0
   def health(self):return {"tools":["calculator"],"models":[{"provider":"nvidia","model":"nvidia/nemotron","enabled":True,"health":"UNAVAILABLE","roles":["reasoning"]}]}
   def retrieve_context(self,*a):return {"rendered":"","source":"test"}
   def plan(self,*a):raise RuntimeError("nemotron_unavailable")
   def invoke(self,*a):self.invoked+=1;raise AssertionError("must not execute")
  with tempfile.TemporaryDirectory() as d:
   g=G();r=PersonalAgent(Gen2Store(Path(d)/"x.db"),g,planner_retries=0).start("calculate 2+2")
   self.assertIn(r["status"],{"WAITING","BLOCKED"});self.assertEqual(g.invoked,0)
