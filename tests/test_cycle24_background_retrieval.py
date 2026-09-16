import tempfile,unittest
from pathlib import Path
from sparkle_gen2.background import BackgroundTaskService
from sparkle_gen2.retrieval import RetrievalQualityEvaluator,SemanticRetrievalRuntime
from sparkle_gen2.storage import Gen2Store

class Agent:
    def resume(self,g):return {'status':'BLOCKED','approvals':[]}
def embed(text):
    text=text.lower();return [1.0 if 'cat' in text else 0.0,1.0 if 'dog' in text else 0.0]
def rerank(q,items):return sorted(items,key=lambda d:0 if d['id']=='cat' else 1)

class Cycle24Tests(unittest.TestCase):
    def test_background_inspect_retry_recover_lifecycle(self):
        with tempfile.TemporaryDirectory() as d:
            s=Gen2Store(Path(d)/'x.db');svc=BackgroundTaskService(s,lambda:Agent());t=svc.create('g');blocked=svc.resume(t.background_id);self.assertEqual(blocked.state,'BLOCKED')
            self.assertEqual(svc.inspect(t.background_id).background_id,t.background_id);retry=svc.retry(t.background_id);self.assertEqual(retry.state,'QUEUED');self.assertEqual(svc.recover(t.background_id).state,'QUEUED')
    def test_retry_rejects_completed(self):
        with tempfile.TemporaryDirectory() as d:
            s=Gen2Store(Path(d)/'x.db');svc=BackgroundTaskService(s,lambda:Agent());t=svc.create('g');t.state='COMPLETED';s.save_background_task(t)
            with self.assertRaises(ValueError):svc.retry(t.background_id)
    def test_retrieval_quality_is_independently_evaluated_from_labels(self):
        runtime=SemanticRetrievalRuntime(embed,rerank);cases=[{'query':'cat','documents':[{'id':'dog','text':'dog animal'},{'id':'cat','text':'cat animal'}],'relevant_ids':['cat']}]
        r=RetrievalQualityEvaluator().evaluate(runtime,cases,k=2);self.assertTrue(r['verified']);self.assertEqual(r['mrr'],1.0);self.assertEqual(r['recall_at_k'],1.0)
    def test_embedding_dependency_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError,'embedding_provider'):SemanticRetrievalRuntime().retrieve('q',[],k=1)
if __name__=='__main__':unittest.main()
