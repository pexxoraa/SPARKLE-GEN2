import json,threading,tempfile,unittest
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
from sparkle_gen2.provider_embeddings import OllamaEmbedder,OllamaEmbeddingConfig
from sparkle_gen2.retrieval import PersistentSemanticIndex,RetrievalQualityEvaluator,SemanticRetrievalRuntime
from sparkle_gen2.storage import Gen2Store

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        body=json.dumps({'models':[{'name':'embed:test'}]}).encode();self.send_response(200);self.end_headers();self.wfile.write(body)
    def do_POST(self):
        n=int(self.headers.get('Content-Length','0'));req=json.loads(self.rfile.read(n));text=req['input']
        vec=[1.0,0.0] if 'cat' in text.lower() else [0.0,1.0]
        body=json.dumps({'embeddings':[vec]}).encode();self.send_response(200);self.end_headers();self.wfile.write(body)

class Cycle37Tests(unittest.TestCase):
    def setUp(self):
        self.s=HTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=self.s.serve_forever,daemon=True).start();self.e=OllamaEmbedder(OllamaEmbeddingConfig('embed:test',f'http://127.0.0.1:{self.s.server_port}',5))
    def tearDown(self):self.s.shutdown();self.s.server_close()
    def test_embedding_transport_and_persistent_restart_index(self):
        self.assertEqual(self.e.health()['status'],'HEALTHY');self.assertEqual(self.e('cat'),[1.0,0.0])
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'x.db';store=Gen2Store(path);idx=PersistentSemanticIndex(store,self.e);idx.upsert('cat','cat animal',metadata={'source':'a'});idx.upsert('dog','dog animal',metadata={'source':'b'});self.assertEqual(idx.search('cat',k=1)[0]['id'],'cat')
            restarted=PersistentSemanticIndex(Gen2Store(path),self.e);self.assertEqual(restarted.search('cat',k=1)[0]['metadata']['source'],'a')
    def test_quality_evaluator_verifies_external_embedding_order(self):
        runtime=SemanticRetrievalRuntime(self.e);cases=[{'query':'cat','documents':[{'id':'dog','text':'dog animal'},{'id':'cat','text':'cat animal'}],'relevant_ids':['cat']}];q=RetrievalQualityEvaluator().evaluate(runtime,cases,k=1);self.assertEqual(q['mrr'],1.0);self.assertEqual(q['recall_at_k'],1.0);self.assertTrue(q['verified'])
if __name__=='__main__':unittest.main()
