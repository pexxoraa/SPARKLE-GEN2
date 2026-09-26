import tempfile,unittest
from pathlib import Path
from sparkle_gen2.mobile import MobilePlatformAdapter
from sparkle_gen2.notifications import NotificationCenter
from sparkle_gen2.self_improvement import ControlledImprovementPipeline
from sparkle_gen2.storage import Gen2Store

class MobileTarget:
    def install(self,a):return {'installed':a}
    def authenticate(self,r):return {'authenticated_ref':r}
    def execute(self,o,p):return {'operation':o,'payload':p}
    def persist(self):return {'persisted':True}
    def reopen(self,a):return {'reopened':a}
    def sync(self):return {'synced':True}
    def notify(self):return {'notified':True}
    def verify(self,o,e):return {'verified':e['persist']['persisted'] and e['sync']['synced'],'method':'target_reread'}
    def logout(self):return {'logged_out':True}

class Cycle26Tests(unittest.TestCase):
    def test_notifications_persist_read_state_across_restart(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.db';s=Gen2Store(p);c=NotificationCenter(s);n=c.create('task','Title','Body');c.read(n.notification_id);r=NotificationCenter(Gen2Store(p));self.assertEqual(r.items[n.notification_id].status,'READ')
    def test_self_improvement_persists_full_gated_lifecycle_and_install_verification(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.db';s=Gen2Store(p);pipe=ControlledImprovementPipeline(s,installer=lambda c:{'registered':True,'id':c.candidate_id});gap=pipe.discover('context','missing source');c=pipe.propose('context','add source',gap=gap['gap']);pipe.implement(c.candidate_id,{'commit':'abc'});pipe.record_tests(c.candidate_id,True);pipe.record_security(c.candidate_id,True,{'verified':True,'method':'bounded security review'});pipe.review(c.candidate_id,True)
            with self.assertRaises(PermissionError):pipe.approve(c.candidate_id,'model')
            pipe.approve(c.candidate_id,'human');out=pipe.install(c.candidate_id);self.assertTrue(out['verification']['registered']);recovered=ControlledImprovementPipeline(Gen2Store(p));self.assertEqual(recovered.items[c.candidate_id].status,'INSTALLED')
    def test_mobile_lifecycle_complete_with_injected_target_and_fails_closed_without_target(self):
        with self.assertRaisesRegex(RuntimeError,'mobile_target'):MobilePlatformAdapter().lifecycle('app','ref','sync',{},approved=True)
        m=MobilePlatformAdapter(MobileTarget());r=m.lifecycle('app','secret-ref','create',{'x':1},approved=True);self.assertTrue(r['verification']['verified']);self.assertTrue(m.logout()['logged_out'])
    def test_mobile_lifecycle_requires_approval(self):
        with self.assertRaises(PermissionError):MobilePlatformAdapter(MobileTarget()).lifecycle('app','ref','x',{},approved=False)
if __name__=='__main__':unittest.main()
