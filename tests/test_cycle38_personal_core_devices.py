import json,tempfile,threading,unittest,urllib.error,urllib.request
from pathlib import Path
from sparkle_gen2.device_identity import DeviceIdentityService
from sparkle_gen2.device_routing import DeviceRouter
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.personal_core import Handler,build_server

class FakeAgent:
    def __init__(self,store):self.store=store;self.n=0
    def start(self,text):
        self.n+=1;gid=f'g{self.n}';return {'goal_id':gid,'status':'COMPLETED','text':'Done: '+text,'checked':['calculator'],'verified':['step'],'approvals':[]}
    def continue_goal(self,gid,text):return {'goal_id':gid,'status':'COMPLETED','text':'Continued: '+text,'checked':['calculator'],'verified':['step'],'approvals':[]}
    def resume(self,gid):return self.continue_goal(gid,'resume')
    def decide_approval(self,*a,**k):return {'status':'APPROVED'}
class Sessions:
    def __init__(self,store):self.store=store
    def create(self,goal_id=None):
        from sparkle_gen2.sessions import Session
        from sparkle_gen2.core_time import now
        s=Session('s'+str(len(self.store.all_sessions())+1),goal_id,now(),now());self.store.save_session(s);return s
    def recover(self,sid):return self.store.load_session(sid)
    def attach_goal(self,sid,gid):s=self.recover(sid);s.active_goal_id=gid;self.store.save_session(s);return s
class Core:
    def __init__(self,store):
        from sparkle_gen2.conversations import ConversationService
        from sparkle_gen2.notifications import NotificationCenter
        self.store=store;self.devices=DeviceIdentityService(store);self.router=DeviceRouter(self.devices);self.agent=FakeAgent(store);self.sessions=Sessions(store);self.conversations=ConversationService(store,self.sessions,self.agent);self.notifications=NotificationCenter(store)
    def state(self,scopes=None):
        scopes=set(scopes or []);out={}
        if 'conversation' in scopes:out['sessions']=self.store.all_sessions()
        if 'device_management' in scopes:out['devices']=self.devices.list()
        if 'notifications' in scopes:out['notifications']=[]
        if 'approvals' in scopes:out['pending_approvals']=[]
        if 'task_status' in scopes:out.update({'background_tasks':[],'goals':[],'tasks':[]})
        return out
    def task_view(self):return []

def request(url,*,token=None,data=None):
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    req=urllib.request.Request(url,data=(json.dumps(data).encode() if data is not None else None),headers=headers,method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(req,timeout=5) as r:return r.status,dict(r.headers),json.loads(r.read())

class Cycle38Tests(unittest.TestCase):
    def test_device_enroll_route_revoke_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'x.db';store=Gen2Store(path);svc=DeviceIdentityService(store);code=svc.create_enrollment_code()['code'];a,ta=svc.enroll(code,name='Laptop',kind='laptop',os_name='Linux',capabilities=['conversation','ros2']);code=svc.create_enrollment_code()['code'];b,tb=svc.enroll(code,name='Phone',kind='phone',os_name='Android',capabilities=['conversation','notifications']);r=DeviceRouter(svc);self.assertEqual(r.select('ros2')['device']['device_id'],a.device_id);self.assertEqual(svc.authenticate(tb)['name'],'Phone');DeviceIdentityService(Gen2Store(path)).revoke(b.device_id)
            with self.assertRaises(PermissionError):DeviceIdentityService(Gen2Store(path)).authenticate(tb)
    def test_real_http_two_devices_share_same_session_and_static_shell(self):
        with tempfile.TemporaryDirectory() as d:
            core=Core(Gen2Store(Path(d)/'x.db'));server=build_server(core,'127.0.0.1',0);threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_address[1]}'
            try:
                code=core.devices.create_enrollment_code()['code'];_,_,e1=request(base+'/api/enroll',data={'code':code,'name':'Laptop','kind':'laptop','os':'Linux','capabilities':['conversation','task_status','device_management']});code=core.devices.create_enrollment_code()['code'];_,_,e2=request(base+'/api/enroll',data={'code':code,'name':'Phone','kind':'phone','os':'Android','capabilities':['conversation','task_status','device_management']})
                _,_,chat=request(base+'/api/chat',token=e1['token'],data={'text':'Check robotics','session_id':None});sid=chat['session_id'];_,_,chat2=request(base+'/api/chat',token=e2['token'],data={'text':'continue','session_id':sid});self.assertEqual(chat2['session_id'],sid);self.assertEqual(chat2['result']['goal_id'],chat['result']['goal_id']);self.assertEqual(core.agent.n,1);_,_,msgs=request(base+f'/api/sessions/{sid}/messages',token=e1['token']);self.assertEqual([m['text'] for m in msgs['messages'] if m['role']=='user'],['Check robotics','continue'])
                with self.assertRaises(urllib.error.HTTPError) as denied:request(base+'/api/notifications',token=e2['token'])
                try:self.assertEqual(denied.exception.code,401)
                finally:denied.exception.close()
                with urllib.request.urlopen(base+'/',timeout=5) as r:html=r.read().decode();headers=dict(r.headers)
                self.assertIn('What should we move forward?',html);self.assertIn('Content-Security-Policy',headers)
            finally:server.shutdown();server.server_close()
    def test_web_enrollment_uses_httponly_cookie_and_scope_denial(self):
        with tempfile.TemporaryDirectory() as d:
            core=Core(Gen2Store(Path(d)/'x.db'));server=build_server(core,'127.0.0.1',0);threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_address[1]}'
            try:
                code=core.devices.create_enrollment_code()['code'];req=urllib.request.Request(base+'/api/enroll',data=json.dumps({'code':code,'name':'Web','kind':'tablet','os':'PWA','capabilities':['conversation'],'client':'web'}).encode(),headers={'Content-Type':'application/json'},method='POST')
                with urllib.request.urlopen(req,timeout=5) as r:body=json.loads(r.read());cookie=r.headers['Set-Cookie']
                self.assertNotIn('token',body);self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Strict',cookie)
                cookie_pair=cookie.split(';',1)[0];state_req=urllib.request.Request(base+'/api/state',headers={'Cookie':cookie_pair})
                with urllib.request.urlopen(state_req,timeout=5) as r:value=json.loads(r.read())
                self.assertIn('sessions',value);self.assertNotIn('notifications',value)
            finally:server.shutdown();server.server_close()

    def test_nonloopback_requires_tls(self):
        with self.assertRaisesRegex(ValueError,'requires_tls'):build_server(Core(Gen2Store(Path(tempfile.mkdtemp())/'x.db')),'0.0.0.0',0)
if __name__=='__main__':unittest.main()
