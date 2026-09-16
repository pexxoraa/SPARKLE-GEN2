import json,tempfile,threading,unittest
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
from sparkle_gen2.activation_evidence import record_activation
from sparkle_gen2.default_acceptance import build_acceptance_matrix
from sparkle_gen2.models import Goal
from sparkle_gen2.provider_planners import OllamaPlannerModel,PlannerProviderConfig

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        body=json.dumps({'models':[{'name':'qwen:test'}]}).encode();self.send_response(200);self.end_headers();self.wfile.write(body)
    def do_POST(self):
        n=int(self.headers.get('Content-Length','0'));req=json.loads(self.rfile.read(n));self.server.seen=req
        plan={'steps':[{'step_id':'s1','objective':'inspect','required_capabilities':['skill_search'],'depends_on':[],'success_criteria':['verified'],'arguments':{'query':'x'},'timeout_seconds':30,'retry_limit':0}], 'success_criteria':[{'description':'verified','verification_method':'all_steps_verified'}],'risk':'LOW','confidence':.9,'unresolved_questions':[]}
        body=json.dumps({'model':'qwen:test','created_at':'req1','message':{'content':json.dumps(plan)}}).encode();self.send_response(200);self.end_headers();self.wfile.write(body)

class Cycle34Tests(unittest.TestCase):
    def test_loopback_ollama_planner_produces_structured_provenance(self):
        server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            p=OllamaPlannerModel(PlannerProviderConfig('ollama','qwen:test',f'http://127.0.0.1:{server.server_port}',5));self.assertEqual(p.health()['status'],'HEALTHY')
            goal=Goal('g','find skill','find skill');proposal,prov=p.propose(goal,{},['skill_search']);self.assertEqual(proposal.steps[0].required_capabilities,['skill_search']);self.assertEqual(prov.provider,'ollama');self.assertFalse(server.seen['think'])
        finally:server.shutdown();server.server_close()
    def test_plaintext_nonloopback_planner_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'loopback'):OllamaPlannerModel(PlannerProviderConfig('ollama','m','http://192.168.1.2:11434',5))
    def test_runtime_evidence_overlays_environment_status_without_baking_it_into_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'e.json';record_activation('live_model_planning','LIVE_VERIFIED','real external call',provider='ollama',environment='loopback',test_id='cycle34',path=p)
            self.assertEqual({x['capability']:x['status'] for x in build_acceptance_matrix().summary()}['live_model_planning'],'EXTERNALLY_BLOCKED')
            item={x['capability']:x for x in build_acceptance_matrix(p).summary()}['live_model_planning'];self.assertEqual(item['status'],'LIVE_VERIFIED');self.assertIn('provider=ollama',item['evidence'])
if __name__=='__main__':unittest.main()
