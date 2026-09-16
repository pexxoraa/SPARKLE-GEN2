import tempfile,unittest
from pathlib import Path
from sparkle_gen2.background import BackgroundTaskService
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.worker import BackgroundWorker

class Agent:
    def resume(self,gid):return {'status':'COMPLETED','approvals':[]}

class Cycle13WorkerTests(unittest.TestCase):
    def test_worker_recovers_queued_tasks_in_bounded_pass(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.sqlite3');svc=BackgroundTaskService(store,Agent);t=svc.create('g1')
            out=BackgroundWorker(svc).run_once(max_tasks=1);self.assertEqual(len(out),1);self.assertEqual(store.load_background_task(t.background_id).state,'COMPLETED')
    def test_worker_skips_paused_and_enforces_budget(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.sqlite3');svc=BackgroundTaskService(store,Agent)
            a=svc.create('g1');b=svc.create('g2');svc.pause(a.background_id)
            out=BackgroundWorker(svc).run_once(max_tasks=1);self.assertEqual(len(out),1);self.assertEqual(store.load_background_task(a.background_id).state,'PAUSED');self.assertEqual(store.load_background_task(b.background_id).state,'COMPLETED')
            with self.assertRaises(ValueError):BackgroundWorker(svc).run_once(max_tasks=0)
if __name__=='__main__':unittest.main()
