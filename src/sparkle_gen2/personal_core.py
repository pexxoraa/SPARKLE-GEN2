from __future__ import annotations
import base64,binascii,json,os,ssl,sys
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs,urlparse
from sparkle.content import ContentEnvelope,ContentPart
from sparkle.contracts import Message
from sparkle.model import ModelRequest
from .background import BackgroundTaskService
from .autonomy import AutonomyController
from .cli import build_components,data_path
from .conversations import ConversationService
from .device_identity import DeviceIdentityService
from .device_routing import DeviceRouter
from .multimodal import MultimodalGateway
from .notifications import NotificationIntelligenceService
from .voice_runtime import VoiceInputFrame,VoiceSessionService
from .core_time import now

class PersonalCore:
    def __init__(self,components=None):
        self.store,self.agent,self.sessions=components or build_components(activate_external_connectors=True);self.devices=DeviceIdentityService(self.store);self.router=DeviceRouter(self.devices);self.notifications=getattr(self.agent,'notifications',None) or NotificationIntelligenceService(self.store);self.delivery=getattr(self.notifications,'delivery',None);self.conversations=ConversationService(self.store,self.sessions,self.agent);self.voice=VoiceSessionService(self.store,model_manager=getattr(self.agent.gen1,'model_manager',None),conversation_service=self.conversations);self.multimodal=MultimodalGateway();self.background=BackgroundTaskService(self.store,lambda:self.agent,notifier=self.notifications);self.autonomy=AutonomyController(self.store);self.operations=self.agent.operations
    @staticmethod
    def _voice_payload(response):
        value=response.to_dict(include_audio=False)
        value['audio_chunks']=[x.metadata()|{'audio_base64':base64.b64encode(bytes(x.audio)).decode('ascii')} for x in response.audio_chunks]
        return value
    def voice_start(self,*,owner_user_id='user',conversation_session_id=None,classification='PRIVATE',persist_transcript=True):
        session=self.voice.create(owner_user_id=owner_user_id,conversation_session_id=conversation_session_id,classification=classification,persist_transcript=bool(persist_transcript))
        connected=self.voice.connect(session.session_id,owner_user_id=owner_user_id)
        return connected.to_dict()
    def voice_push(self,session_id,*,audio_base64,sequence,final=False,owner_user_id='user'):
        if not isinstance(audio_base64,str) or not audio_base64 or len(audio_base64)>100_000:raise ValueError('voice_audio_payload_invalid_or_too_large')
        try:raw=base64.b64decode(audio_base64,validate=True)
        except (binascii.Error,ValueError) as exc:raise ValueError('voice_audio_payload_invalid_base64') from exc
        frame=VoiceInputFrame(str(session_id),int(sequence),raw,now(),final=bool(final))
        return self._voice_payload(self.voice.push(frame,owner_user_id=owner_user_id))
    def multimodal_send(self,*,modality,mime_type,data_base64,prompt='',session_id=None,device_id=None):
        if modality not in {'image','audio'}:raise ValueError('personal_core_multimodal_modality_not_supported')
        if not isinstance(data_base64,str) or not data_base64 or len(data_base64)>5_500_000:raise ValueError('multimodal_payload_invalid_or_too_large')
        if not isinstance(prompt,str) or len(prompt)>2000:raise ValueError('multimodal_prompt_invalid_or_too_large')
        try:raw=base64.b64decode(data_base64,validate=True)
        except (binascii.Error,ValueError) as exc:raise ValueError('multimodal_payload_invalid_base64') from exc
        if len(raw)>4_000_000:raise ValueError('multimodal_payload_too_large')
        item,raw=self.multimodal.prepare_bytes(raw,modality=modality,mime_type=mime_type)
        if len(raw)>4_000_000:raise ValueError('normalized_multimodal_payload_too_large')
        manager=getattr(self.agent.gen1,'model_manager',None)
        if manager is None:return {'status':'BLOCKED','reason':'model_manager_unavailable','media':item.to_dict()}
        routed=self.multimodal.route(item,manager)
        if routed.get('status')=='BLOCKED':return {'status':'BLOCKED','reason':'model_capability_unavailable','media':routed.get('media'),'route':routed.get('route')}
        if modality!='image':return {'status':'BLOCKED','reason':'audio_requires_realtime_voice_session','media':routed.get('media'),'route':routed.get('route')}
        instruction=prompt.strip() or 'Describe the user-supplied image accurately and concisely.'
        envelope=ContentEnvelope([ContentPart.text(instruction),ContentPart.binary('image',raw,media_type=item.mime_type)])
        request=ModelRequest(messages=[Message(role='user',content=envelope)],thinking=False,max_output_tokens=256)
        result=manager.complete(request,['multimodal','reasoning'],input_modalities=['text','image'],output_modalities=['text'])
        interpretation=' '.join(str(result['response'].text).split())[:4000]
        if not interpretation:raise RuntimeError('multimodal_interpretation_empty')
        provenance=result.get('provenance') or {}
        model_ref=f"{provenance.get('provider','unknown')}/{provenance.get('model','unknown')}"
        agent_input=(prompt.strip()+'\n\n' if prompt.strip() else '')+f'Image interpretation from {model_ref}: {interpretation}'
        conversation=self.conversations.send(agent_input,session_id=session_id,device_id=device_id)
        return {'status':'COMPLETED','session_id':conversation['session_id'],'message':conversation['message'],'result':conversation['result'],'media':{'media_id':item.media_id,'modality':item.modality,'mime_type':item.mime_type,'size_bytes':item.size_bytes,'sha256':item.sha256,'metadata_stripped':True},'model':{'provider':provenance.get('provider'),'model':provenance.get('model'),'fallback':bool(provenance.get('fallback'))},'interpretation_chars':len(interpretation)}
    def operations_snapshot(self,scopes=None,*,owner_user_id='user',day=None):
        if self.operations is None:raise RuntimeError('operations_surface_unavailable')
        scopes=set(scopes or []);value=self.operations.snapshot(owner_user_id=owner_user_id,day=day)
        if 'approvals' not in scopes:
            value['operations']['pending_approvals']=[]
            if value.get('next_action',{}).get('source')=='approval':value['next_action']={'status':'REDACTED','title':'Approval pending','source':'approval'}
        if 'notifications' not in scopes:value['today']['notifications']=[]
        if 'device_management' not in scopes:
            value['intelligence']['devices']={'status':'UNAVAILABLE','items':[]};value['intelligence']['world_state']={'status':'UNAVAILABLE','items':[]}
        return value
    def decide_approval(self,approval_id,decision,*,owner_user_id='user',actor='dashboard'):
        approval=self.store.load_approval(approval_id);goal=self.store.load_goal(approval.goal_id)
        if goal.user_id!=owner_user_id:raise PermissionError('approval_owner_mismatch')
        self.agent.decide_approval(approval_id,decision,actor=actor)
        result=self.agent.resume(approval.goal_id)
        voice=[]
        for row in self.store.voice_sessions(owner_user_id=owner_user_id):
            if row.get('pending_goal_id')!=approval.goal_id:continue
            try:voice.append(self._voice_payload(self.voice.complete_pending(row['session_id'],owner_user_id=owner_user_id,agent_result=result)))
            except Exception as exc:voice.append({'session_id':row['session_id'],'status':'UNAVAILABLE','error_type':type(exc).__name__})
        reread=self.store.load_approval(approval_id).to_dict()
        return {'approval':reread,'goal':result,'voice':voice}
    def decide_operations_approval(self,approval_id,decision,*,owner_user_id='user',actor='dashboard'):
        value=self.decide_approval(approval_id,decision,owner_user_id=owner_user_id,actor=actor)
        value['snapshot']=self.operations.snapshot(owner_user_id=owner_user_id)
        return value
    def state(self,scopes=None):
        scopes=set(scopes or []);out={}
        if 'task_status' in scopes:out.update({'goals':self.store.recent_goals(50),'tasks':self.store.all_task_runs(100),'background_tasks':[x.to_dict() for x in self.store.background_tasks()]})
        if 'approvals' in scopes:out['pending_approvals']=[a.to_dict() for a in self.store.all_approvals() if a.status.value=='PENDING']
        if 'notifications' in scopes:
            out['notifications']=self.notifications.attention('user',limit=50)
            if self.delivery is not None:out['notification_channels']=self.delivery.channel_states('user');out['notification_delivery']={'recent':self.delivery.attempts('user')[-50:]}
        if 'device_management' in scopes:out['devices']=self.devices.list();out['autonomy']=self.autonomy.get()
        else:out['devices']=[]
        if 'conversation' in scopes:out['sessions']=self.store.all_sessions(50)
        if 'artifacts' in scopes:
            fn=getattr(self.agent.gen1,'artifacts',None);out['artifacts']=fn(50) if callable(fn) else []
        return out
    def close(self):
        connectors=getattr(self.agent,'connectors',None)
        closed=connectors.close() if connectors is not None and callable(getattr(connectors,'close',None)) else {'closed_connectors':[]}
        return {'status':'closed','connectors':closed.get('closed_connectors',[])}
    def task_view(self):
        goals={g['goal_id']:g for g in self.store.recent_goals(100)};out=[]
        for run in self.store.all_task_runs(100):
            g=goals.get(run['goal_id'],{});total=len(run.get('completed_steps',[]))+len(run.get('pending_steps',[]))+len(run.get('failed_steps',[]));progress=100 if run.get('status')=='COMPLETED' else round(100*len(run.get('completed_steps',[]))/max(1,total))
            out.append({'goal_id':run['goal_id'],'goal':g.get('user_request',''),'status':g.get('status',run.get('status')),'progress':progress,'current_operation':run.get('current_step'),'started':run.get('started_at'),'approvals':run.get('approvals',[]),'artifacts':run.get('artifacts',[]),'trace_id':run.get('trace_id')})
        return out

class Handler(BaseHTTPRequestHandler):
    server_version='SPARKLE-Personal-Core/1'
    def log_message(self,fmt,*args):pass
    @property
    def core(self):return self.server.core
    def _json(self,status,value,headers=None):
        raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer');self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'");self.send_header('Content-Length',str(len(raw)));[(self.send_header(k,v)) for k,v in (headers or {}).items()];self.end_headers();self.wfile.write(raw)
    def _body(self,max_bytes=1_000_000):
        try:n=int(self.headers.get('Content-Length','0'))
        except ValueError:raise ValueError('invalid_content_length')
        if n<0 or n>max_bytes:raise ValueError('request_too_large')
        raw=self.rfile.read(n) if n else b'{}';value=json.loads(raw.decode())
        if not isinstance(value,dict):raise ValueError('json_object_required')
        return value
    def _device_token(self):
        auth=self.headers.get('Authorization','')
        if auth.startswith('Bearer '):return auth[7:]
        raw=self.headers.get('Cookie','')
        if raw:
            cookie=SimpleCookie();cookie.load(raw);item=cookie.get('sparkle_device')
            if item and item.value:return item.value
        raise PermissionError('authentication_required')
    def _device(self):return self.core.devices.authenticate(self._device_token())
    @staticmethod
    def _scope(device,scope):
        if scope not in set(device.get('capabilities',[])):raise PermissionError('device_scope_denied:'+scope)
    def _static(self,path):
        root=Path(__file__).with_name('web').resolve();name='index.html' if path in {'/','/index.html'} else path.lstrip('/');target=(root/name).resolve()
        if root not in target.parents or not target.is_file():return False
        types={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'application/javascript; charset=utf-8','.json':'application/json; charset=utf-8','.svg':'image/svg+xml'};raw=target.read_bytes();self.send_response(200);self.send_header('Content-Type',types.get(target.suffix,'application/octet-stream'));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'");self.send_header('Cache-Control','no-cache' if target.name=='index.html' else 'public, max-age=300');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return True
    def do_GET(self):
        u=urlparse(self.path)
        try:
            if u.path=='/health':return self._json(200,{'ok':True,'service':'sparkle-personal-core','private_default':True})
            if not u.path.startswith('/api/'):
                if self._static(u.path):return
                return self._json(404,{'error':'not_found'})
            device=self._device()
            if u.path=='/api/state':return self._json(200,self.core.state(device.get('capabilities',[])))
            if u.path=='/api/operations':
                self._scope(device,'task_status');q=parse_qs(u.query);day=q.get('day',[None])[0];return self._json(200,self.core.operations_snapshot(device.get('capabilities',[]),owner_user_id='user',day=day))
            if u.path=='/api/tasks':self._scope(device,'task_status');return self._json(200,{'tasks':self.core.task_view()})
            if u.path=='/api/approvals':self._scope(device,'approvals');return self._json(200,{'approvals':[a.to_dict() for a in self.core.store.all_approvals() if a.status.value=='PENDING']})
            if u.path=='/api/notifications':self._scope(device,'notifications');return self._json(200,{'notifications':self.core.notifications.attention('user',limit=100)})
            if u.path=='/api/voice/status':
                self._scope(device,'conversation');return self._json(200,self.core.voice.health())
            if u.path.startswith('/api/voice/sessions/'):
                self._scope(device,'conversation');parts=[x for x in u.path.split('/') if x]
                if len(parts)==4 and parts[:3]==['api','voice','sessions']:
                    return self._json(200,self.core.voice.inspect(parts[3],owner_user_id='user'))
            if u.path=='/api/notification-channels':
                self._scope(device,'notifications');return self._json(200,{'channels':[] if self.core.delivery is None else self.core.delivery.channel_states('user')})
            if u.path=='/api/notification-deliveries/pending':
                self._scope(device,'notifications');q=parse_qs(u.query);channel=q.get('channel',['desktop'])[0];return self._json(200,{'attempts':[] if self.core.delivery is None else self.core.delivery.pending('user',channel=channel,device_id=device['device_id'])})
            if u.path.startswith('/api/notification-deliveries/'):
                self._scope(device,'notifications');parts=[x for x in u.path.split('/') if x]
                if len(parts)==3 and self.core.delivery is not None:return self._json(200,self.core.delivery.inspect(owner_user_id='user',attempt_id=parts[2]))
            if u.path=='/api/devices':self._scope(device,'device_management');return self._json(200,{'devices':self.core.devices.list()})
            if u.path=='/api/artifacts':self._scope(device,'artifacts');fn=getattr(self.core.agent.gen1,'artifacts',None);return self._json(200,{'artifacts':fn(100) if callable(fn) else []})
            if u.path.startswith('/api/artifacts/') and u.path.endswith('/download'):
                self._scope(device,'artifacts');parts=[x for x in u.path.split('/') if x];aid=int(parts[2]);fn=getattr(self.core.agent.gen1,'artifact_content',None);value=fn(aid) if callable(fn) else None
                if not value:return self._json(404,{'error':'artifact_not_found'})
                raw=value['content'];rows=getattr(self.core.agent.gen1,'artifacts',lambda limit:[])(100);row=next((x for x in rows if x.get('artifact_id')==aid),{});media=str((row.get('manifest') or {}).get('media_type') or 'application/zip');self.send_response(200);self.send_header('Content-Type',media);self.send_header('Content-Disposition',f"attachment; filename={value['name']}");self.send_header('X-Artifact-SHA256',value['sha256']);self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
            if u.path=='/api/settings/autonomy':self._scope(device,'device_management');return self._json(200,self.core.autonomy.get())
            if u.path=='/api/sessions':self._scope(device,'conversation');return self._json(200,{'sessions':self.core.store.all_sessions(100)})
            if u.path.startswith('/api/sessions/') and u.path.endswith('/messages'):
                self._scope(device,'conversation');sid=u.path.split('/')[3];return self._json(200,{'session_id':sid,'messages':self.core.conversations.messages(sid,200)})
            if u.path=='/api/events':
                self._scope(device,'task_status');q=parse_qs(u.query);limit=min(200,max(1,int(q.get('limit',['100'])[0])));after=max(0,int(q.get('after',['0'])[0]));events=[e for e in reversed(self.core.store.recent_events(limit)) if int(e['event_id'])>after];return self._json(200,{'events':events,'device_id':device['device_id'],'cursor':max([after]+[int(e['event_id']) for e in events])})
            return self._json(404,{'error':'not_found'})
        except PermissionError as exc:return self._json(401,{'error':str(exc)})
        except (KeyError,ValueError) as exc:return self._json(400,{'error':str(exc)})
        except Exception as exc:return self._json(500,{'error':'internal_error','type':type(exc).__name__})
    def do_POST(self):
        u=urlparse(self.path)
        try:
            body=self._body(6_000_000 if u.path=='/api/multimodal' else 1_000_000)
            if u.path=='/api/enroll':
                d,t=self.core.devices.enroll(body.get('code',''),name=body.get('name',''),kind=body.get('kind',''),os_name=body.get('os',''),capabilities=body.get('capabilities',[]));web=body.get('client')=='web';headers={'Set-Cookie':f'sparkle_device={t}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000'} if web else {};return self._json(201,{'device':d.to_dict(),**({} if web else {'token':t})},headers)
            device=self._device()
            if u.path=='/api/logout':return self._json(200,{'ok':True},{'Set-Cookie':'sparkle_device=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'})
            if u.path=='/api/voice/sessions':
                self._scope(device,'conversation');value=self.core.voice_start(owner_user_id='user',conversation_session_id=body.get('conversation_session_id'),classification=body.get('classification','PRIVATE'),persist_transcript=body.get('persist_transcript',True));return self._json(201,value)
            voice_parts=[x for x in u.path.split('/') if x]
            if len(voice_parts)==5 and voice_parts[:3]==['api','voice','sessions']:
                self._scope(device,'conversation');sid=voice_parts[3];action=voice_parts[4]
                if action=='audio':return self._json(200,self.core.voice_push(sid,audio_base64=body.get('audio_base64',''),sequence=body.get('sequence',0),final=body.get('final',False),owner_user_id='user'))
                if action=='interrupt':return self._json(200,self.core.voice.interrupt(sid,owner_user_id='user').to_dict())
                if action=='close':return self._json(200,self.core.voice.close(sid,owner_user_id='user').to_dict())
            if u.path=='/api/chat':self._scope(device,'conversation');return self._json(200,self.core.conversations.send(body.get('text',''),session_id=body.get('session_id'),device_id=device['device_id']))
            if u.path=='/api/multimodal':
                self._scope(device,'conversation');value=self.core.multimodal_send(modality=body.get('modality',''),mime_type=body.get('mime_type'),data_base64=body.get('data_base64',''),prompt=body.get('prompt',''),session_id=body.get('session_id'),device_id=device['device_id']);return self._json(200 if value.get('status')=='COMPLETED' else 409,value)
            if u.path=='/api/background':
                self._scope(device,'task_status');goal_id=str(body.get('goal_id',''));self.core.store.load_goal(goal_id);task=self.core.background.create(goal_id,max_iterations=int(body.get('max_iterations',100)),time_budget_seconds=float(body.get('time_budget_seconds',300)));return self._json(201,task.to_dict())
            if u.path=='/api/notification-channels/desktop':
                self._scope(device,'notifications')
                if self.core.delivery is None:raise RuntimeError('notification_delivery_unavailable')
                permission=str(body.get('permission','UNKNOWN')).upper();permission='UNKNOWN' if permission=='DEFAULT' else permission
                state=self.core.delivery.register_channel(owner_user_id='user',channel='desktop',device_id=device['device_id'],permission=permission,supported=bool(body.get('supported',False)),configured=permission=='GRANTED',provenance={'client':'personal_core_pwa','device_id':device['device_id']});return self._json(200,state.to_dict())
            parts=[x for x in u.path.split('/') if x]
            if len(parts)==4 and parts[:2]==['api','notification-deliveries'] and parts[3]=='result':
                self._scope(device,'notifications')
                if self.core.delivery is None:raise RuntimeError('notification_delivery_unavailable')
                return self._json(200,self.core.delivery.record_result(parts[2],owner_user_id='user',device_id=device['device_id'],status=body.get('status',''),channel_reference=body.get('channel_reference'),error=body.get('error')))
            if len(parts)==4 and parts[:2]==['api','notification-deliveries'] and parts[3]=='acknowledge':
                self._scope(device,'notifications')
                if self.core.delivery is None:raise RuntimeError('notification_delivery_unavailable')
                return self._json(200,self.core.delivery.acknowledge(parts[2],owner_user_id='user',device_id=device['device_id']))
            if len(parts)==4 and parts[:2]==['api','notification-deliveries'] and parts[3]=='retry':
                self._scope(device,'notifications')
                if self.core.delivery is None:raise RuntimeError('notification_delivery_unavailable')
                return self._json(200,self.core.delivery.retry(parts[2],owner_user_id='user'))
            if len(parts)==5 and parts[:3]==['api','operations','approvals'] and parts[4] in {'approve','reject'}:
                self._scope(device,'approvals');self._scope(device,'task_status');return self._json(200,self.core.decide_operations_approval(parts[3],parts[4],owner_user_id='user',actor='device:'+device['device_id']))
            if len(parts)==4 and parts[:2]==['api','approvals'] and parts[3] in {'approve','reject'}:
                self._scope(device,'approvals')
                return self._json(200,self.core.decide_approval(parts[2],parts[3],owner_user_id='user',actor='device:'+device['device_id']))
            if len(parts)==4 and parts[:2]==['api','background'] and parts[3] in {'pause','resume','retry','cancel'}:
                self._scope(device,'task_status');fn=getattr(self.core.background,parts[3]);return self._json(200,fn(parts[2]).to_dict())
            if len(parts)==4 and parts[:2]==['api','tasks'] and parts[3] in {'resume','cancel','replan'}:
                self._scope(device,'task_status')
                fn=getattr(self.core.agent,parts[3]);return self._json(200,fn(parts[2]))
            if len(parts)==4 and parts[:2]==['api','notifications'] and parts[3]=='read':
                self._scope(device,'notifications');value=self.core.notifications.read(parts[2],owner_user_id='user').to_dict()
                if self.core.delivery is not None:self.core.delivery.acknowledge_notification(parts[2],owner_user_id='user',channel='dashboard')
                return self._json(200,value)
            if len(parts)==4 and parts[:2]==['api','devices'] and parts[3]=='revoke':
                self._scope(device,'device_management')
                if parts[2]==device['device_id']:raise PermissionError('cannot_revoke_current_device_from_same_session')
                return self._json(200,self.core.devices.revoke(parts[2]))
            if len(parts)==4 and parts[:2]==['api','devices'] and parts[3]=='rename':self._scope(device,'device_management');return self._json(200,self.core.devices.rename(parts[2],body.get('name','')))
            if u.path=='/api/settings/autonomy':self._scope(device,'device_management');return self._json(200,self.core.autonomy.set(body.get('mode','')))
            if u.path=='/api/route':self._scope(device,'device_management');return self._json(200,self.core.router.select(body.get('capability',''),preferred_device_id=body.get('preferred_device_id')))
            return self._json(404,{'error':'not_found'})
        except PermissionError as exc:return self._json(403,{'error':str(exc)})
        except (KeyError,ValueError) as exc:return self._json(400,{'error':str(exc)})
        except Exception as exc:return self._json(500,{'error':'internal_error','type':type(exc).__name__})

def build_server(core,host='127.0.0.1',port=8765,*,tls_cert=None,tls_key=None):
    if host not in {'127.0.0.1','localhost','::1'} and not (tls_cert and tls_key):raise ValueError('non_loopback_personal_core_requires_tls')
    server=ThreadingHTTPServer((host,port),Handler);server.core=core
    if tls_cert and tls_key:
        ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.minimum_version=ssl.TLSVersion.TLSv1_2;ctx.load_cert_chain(tls_cert,tls_key);server.socket=ctx.wrap_socket(server.socket,server_side=True)
    return server

def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(prog='sparkle-personal-core');p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8765);p.add_argument('--tls-cert');p.add_argument('--tls-key');p.add_argument('--pair',action='store_true');a=p.parse_args(argv);core=PersonalCore()
    if a.pair:
        pair=core.devices.create_enrollment_code();print('Pairing code:',pair['code']);print('Expires:',pair['expires_at']);core.close();return 0
    server=build_server(core,a.host,a.port,tls_cert=a.tls_cert,tls_key=a.tls_key);scheme='https' if a.tls_cert else 'http';print(f'SPARKLE Personal Core: {scheme}://{a.host}:{server.server_address[1]}')
    try:server.serve_forever()
    finally:server.server_close();core.close()

def entrypoint():return main()
if __name__=='__main__':raise SystemExit(main())
