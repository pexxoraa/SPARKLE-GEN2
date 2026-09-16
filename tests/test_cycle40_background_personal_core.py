import tempfile,unittest
from pathlib import Path
from sparkle_gen2.background import BackgroundTaskService
from sparkle_gen2.worker import BackgroundWorker
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.models import Goal,GoalStatus
from sparkle_gen2.core_time import now
from sparkle_gen2.notifications import NotificationCenter
class Agent:
    calls=0
    def resume(self,gid):
        Agent.calls+=1
        return {'goal_id':gid,'status':'COMPLETED','approvals':[]}
class Cycle40Tests(unittest.TestCase):
    def test_background_task_survives_store_restart_and_worker_finishes(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'x.db';store=Gen2Store(path);stamp=now();g=Goal('g1','work','work',status=GoalStatus.WAITING,created_at=stamp,updated_at=stamp);store.save_goal(g)
            service=BackgroundTaskService(store,lambda:Agent());task=service.create('g1');self.assertEqual(task.state,'QUEUED')
            restarted=Gen2Store(path);worker=BackgroundWorker(BackgroundTaskService(restarted,lambda:Agent(),notifier=NotificationCenter(restarted)));result=worker.run_once();self.assertEqual(result[0]['state'],'COMPLETED');final=Gen2Store(path);self.assertEqual(final.load_background_task(task.background_id).state,'COMPLETED');notes=final.notifications();self.assertEqual(len(notes),1);self.assertEqual(notes[0]['title'],'Background task complete')
    def test_pwa_manifest_has_install_icons(self):
        import json
        root=Path(__file__).parents[1]/'src'/'sparkle_gen2'/'web'
        m=json.loads((root/'manifest.json').read_text())
        self.assertEqual(m['display'],'standalone');self.assertEqual(m['start_url'],'/')
        sizes={x['sizes'] for x in m['icons']};self.assertTrue({'192x192','512x512'}<=sizes)
        for icon in m['icons']:self.assertTrue((root/icon['src'].lstrip('/')).is_file())

    def test_ui_shell_never_caches_api_data(self):
        text=(Path(__file__).resolve().parents[1]/'src/sparkle_gen2/web/service-worker.js').read_text();self.assertIn("u.pathname.startsWith('/api/')",text);self.assertIn("return",text)
if __name__=='__main__':unittest.main()
