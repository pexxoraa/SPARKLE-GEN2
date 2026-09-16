import tempfile,unittest
from datetime import UTC,datetime,timedelta
from pathlib import Path
from sparkle_gen2.gen1_interactions import Gen1BrowserSession,Gen1ComputerSession
from sparkle_gen2.models import PermissionEffect,PermissionStatus
from sparkle_gen2.permission_center import PermissionCenter
from sparkle_gen2.storage import Gen2Store

class Service:
    def __init__(self):self.rev=1;self.events=[];self.mode=None
    def start_session(self,mode,**kwargs):self.mode=mode;self.rev=1;return {'id':'session-1234567890','mode':mode,'status':'active','revision':1}
    def session(self,sid):return {'id':sid,'mode':self.mode,'status':'active','revision':self.rev}
    def browse_session(self,sid,url,expected_revision,**kwargs):
        if expected_revision!=self.rev:raise RuntimeError('revision');self.rev+=1
        out={'final_url':url,'title':'T','text':'ok','status_code':200,'session_revision':self.rev};self.events.append({'id':1,'event':'browse','result':out});return out
    def perform_session(self,sid,action,expected_revision):
        if expected_revision!=self.rev:raise RuntimeError('revision');self.rev+=1
        out={'kind':action['kind'],'completed':True,'evidence':{},'session_revision':self.rev};self.events.append({'id':2,'event':'computer_action','result':out});return out
    def history(self,sid,limit=1):return self.events[-limit:]
    def close_session(self,sid,expected_revision):self.rev+=1;return {'id':sid,'mode':self.mode,'status':'closed','revision':self.rev}
class Gen1:
    def __init__(self):self.system=type('S',(),{'interactions':Service()})()

class Cycle28Tests(unittest.TestCase):
    def test_permission_center_persists_grant_revoke_expire_and_denies_model_grant(self):
        with tempfile.TemporaryDirectory() as d:
            s=Gen2Store(Path(d)/'x.db');c=PermissionCenter(s,'g')
            with self.assertRaises(PermissionError):c.grant('user','x','scope',PermissionEffect.ALLOW,granted_by='model')
            p=c.grant('user','x','scope',PermissionEffect.ALLOW);self.assertEqual(c.authorize('user','x','scope'),PermissionEffect.ALLOW);c.revoke(p.permission_id);self.assertEqual(c.authorize('user','x','scope'),PermissionEffect.DENY)
            e=c.grant('user','y','scope',PermissionEffect.ALLOW,expires_at=(datetime.now(UTC)-timedelta(seconds=1)).isoformat());self.assertEqual({x.permission_id:x for x in c.list()}[e.permission_id].status,PermissionStatus.EXPIRED)
            recovered=PermissionCenter(Gen2Store(Path(d)/'x.db'),'g');self.assertEqual(recovered.authorize('user','x','scope'),PermissionEffect.DENY)
    def test_gen1_browser_session_uses_persisted_revisioned_history(self):
        b=Gen1BrowserSession(Gen1(),['example.com']);r=b.browse('https://example.com');self.assertEqual(r['status_code'],200);self.assertTrue(b.verify_last()['verified']);self.assertEqual(b.close()['status'],'closed')
    def test_gen1_computer_session_uses_allowlisted_session_and_history(self):
        c=Gen1ComputerSession(Gen1(),['click']);r=c.perform({'kind':'click','x':1,'y':2});self.assertTrue(r['completed']);self.assertTrue(c.verify_last()['verified']);c.close()
if __name__=='__main__':unittest.main()
