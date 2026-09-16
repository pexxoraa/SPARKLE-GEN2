import json,threading,unittest
from http.server import BaseHTTPRequestHandler,HTTPServer
from sparkle_gen2.provider_text_roles import OllamaJSONClient,OllamaReranker,OllamaSafetyClassifier,OllamaTextRoleConfig
from sparkle_gen2.safety_runtime import SafetyModelRuntime

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        b=json.dumps({'models':[{'name':'m'}]}).encode();self.send_response(200);self.end_headers();self.wfile.write(b)
    def do_POST(self):
        n=int(self.headers.get('Content-Length','0'));req=json.loads(self.rfile.read(n));text=req['messages'][-1]['content']
        if 'Candidates:' in text: data={'ranked_ids':['cat','dog']}
        else:data={'label':'unsafe','score':.99,'reason_code':'destructive'}
        b=json.dumps({'message':{'content':json.dumps(data)}}).encode();self.send_response(200);self.end_headers();self.wfile.write(b)

class Cycle35Tests(unittest.TestCase):
    def setUp(self):
        self.s=HTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=self.s.serve_forever,daemon=True).start();self.client=OllamaJSONClient(OllamaTextRoleConfig('m',f'http://127.0.0.1:{self.s.server_port}',5))
    def tearDown(self):self.s.shutdown();self.s.server_close()
    def test_reranker_requires_exact_candidate_permutation(self):
        r=OllamaReranker(self.client)('cat',[{'id':'dog','text':'dog'},{'id':'cat','text':'cat'}]);self.assertEqual([x['id'] for x in r],['cat','dog'])
    def test_safety_adapter_is_validated_but_remains_runtime_advisory(self):
        r=SafetyModelRuntime(OllamaSafetyClassifier(self.client)).classify('delete files');self.assertEqual(r['label'],'unsafe');self.assertEqual(r['provider'],'ollama')
if __name__=='__main__':unittest.main()
