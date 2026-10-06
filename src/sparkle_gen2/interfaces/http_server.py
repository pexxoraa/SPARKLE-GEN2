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
from ..background import BackgroundTaskService
from ..autonomy import AutonomyController
from ..runtime import build_components,data_path
from ..application.conversation import ConversationService
from ..device_identity import DeviceIdentityService
from ..device_routing import DeviceRouter
from ..multimodal import MultimodalGateway
from ..notifications import NotificationIntelligenceService
from ..voice_runtime import VoiceInputFrame,VoiceSessionService
from ..core_time import now
from ..domain.models import Goal,GoalStatus
from .http.transport import JsonResponder,JsonRequest,DeviceAuthentication,StaticFileService

from ..application.system.personal_core import PersonalCore

class Handler(BaseHTTPRequestHandler):
    server_version='SPARKLE-Personal-Core/1'
    def log_message(self,fmt,*args):pass
    @property
    def core(self):return self.server.core
    def _json(self,status,value,headers=None):
        return JsonResponder.send(self,status,value,headers)
    def _body(self,max_bytes=1_000_000):
        return JsonRequest.read(self,max_bytes)
    def _owned_goal(self,goal_id):
        goal=self.core.store.load_goal(goal_id)
        if getattr(goal,'user_id','user')!='user':raise PermissionError('goal_owner_mismatch')
        return goal
    def _pending_approvals(self):
        rows=[]
        for approval in self.core.store.all_approvals():
            if approval.status.value!='PENDING':continue
            try:self._owned_goal(approval.goal_id)
            except (PermissionError,KeyError):continue
            rows.append(approval.to_dict())
        return rows
    def _device_token(self):
        return DeviceAuthentication.token(self)
    def _device(self):return self.core.devices.authenticate(self._device_token())
    @staticmethod
    def _scope(device,scope):
        if scope not in set(device.get('capabilities',[])):raise PermissionError('device_scope_denied:'+scope)
    def _static(self,path):
        return StaticFileService(Path(__file__).resolve().parents[1] / 'web').serve(self,path)
    def do_GET(self):
        u=urlparse(self.path)
        try:
            if u.path=='/health':return self._json(200,{'ok':True,'service':'sparkle-personal-core','private_default':True})
            if not u.path.startswith('/api/'):
                if self._static(u.path):return
                return self._json(404,{'error':'not_found'})
            device=self._device()
            if u.path=='/api/state':return self._json(200,self.core.state(device.get('capabilities',[])))
            if u.path=='/api/os':
                self._scope(device,'conversation');return self._json(200,self.core.os_snapshot(owner_user_id='user'))
            if u.path=='/api/conversation/agents':
                self._scope(device,'conversation');return self._json(200,{'agents':self.core.agent_catalog(conversation_only=True),'selected':(self.core.store.load_setting('conversation_agent',{}) or {}).get('agent_id','personal'),'architecture':{'agent_layer':'SPARKLE Agent Registry','model_layer':'Provider Model Router','execution_layer':'PersonalAgent + Gen-1','rule':'agent selection and model selection are independent'}})
            if u.path=='/api/device-agent/targets':
                self._scope(device,'conversation');return self._json(200,{'targets':self.core.device_agent_targets(owner_user_id='user')})
            if u.path=='/api/operations':
                self._scope(device,'task_status');q=parse_qs(u.query);day=q.get('day',[None])[0];return self._json(200,self.core.operations_snapshot(device.get('capabilities',[]),owner_user_id='user',day=day))
            if u.path=='/api/tasks':self._scope(device,'task_status');return self._json(200,{'tasks':self.core.task_view()})
            if u.path=='/api/executions':
                self._scope(device,'task_status');return self._json(200,self.core.inspector.execution_list())
            if u.path.startswith('/api/executions/'):
                self._scope(device,'task_status');return self._json(200,self.core.inspector.execution_detail(u.path.split('/')[3]))
            if u.path in {'/api/knowledge','/api/memory','/api/automations','/api/activity','/api/graph'}:
                self._scope(device,'conversation');method={'/api/knowledge':'knowledge','/api/memory':'memory','/api/automations':'automations','/api/activity':'activity','/api/graph':'graph_snapshot'}[u.path]
                return self._json(200,getattr(self.core.inspector,method)())
            if u.path=='/api/system':
                self._scope(device,'task_status');return self._json(200,self.core.operations_snapshot(device.get('capabilities',[])))
            if u.path=='/api/approvals':self._scope(device,'approvals');return self._json(200,{'approvals':self._pending_approvals()})
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
            if u.path=='/api/conversation/models':self._scope(device,'conversation');return self._json(200,self.core.conversations.model_inventory())
            if u.path=='/api/sessions':self._scope(device,'conversation');return self._json(200,{'sessions':self.core.conversations.session_summaries(100)})
            if u.path.startswith('/api/sessions/') and u.path.endswith('/context'):
                self._scope(device,'conversation');sid=u.path.split('/')[3];s=self.core.conversations.ensure_session(sid);messages=self.core.conversations.messages(sid,200);latest=next((str(x.get('text','')).strip() for x in reversed(messages) if x.get('role')=='user' and str(x.get('text','')).strip()),'');return self._json(200,{'context':self.core.conversations._conversation_context(s,latest)})
            if u.path.startswith('/api/sessions/') and u.path.endswith('/messages'):
                self._scope(device,'conversation');sid=u.path.split('/')[3];return self._json(200,{'session_id':sid,'messages':self.core.conversations.messages(sid,200)})
            if u.path=='/api/events':
                self._scope(device,'task_status');q=parse_qs(u.query);limit=min(200,max(1,int(q.get('limit',['100'])[0])));after=max(0,int(q.get('after',['0'])[0]));owned={g['goal_id'] for g in self.core.store.recent_goals(1000) if g.get('user_id','user')=='user'};events=[e for e in reversed(self.core.store.recent_events(limit)) if int(e['event_id'])>after and e.get('goal_id') in owned];return self._json(200,{'events':events,'device_id':device['device_id'],'cursor':max([after]+[int(e['event_id']) for e in events])})
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
                if action=='audio':
                    try:
                        return self._json(200,self.core.voice_push(sid,audio_base64=body.get('audio_base64',''),sequence=body.get('sequence',0),final=body.get('final',False),owner_user_id='user'))
                    except Exception as exc:
                        reason=type(exc).__name__
                        try: self.core.voice.interrupt(sid,owner_user_id='user')
                        except Exception: pass
                        return self._json(200,{'session_id':sid,'state':'CONNECTED','transcripts':[],'audio_chunks':[],'agent_result':{'text':'I hit a temporary voice interface issue. Please continue speaking; I did not repeat the request automatically.','status':'COMPLETED','voice_retry':True},'provider_result':{'recoverable':True,'provider_error':reason},'provenance':{'capability':'voice_recovery','error_type':reason}})
                if action=='interrupt':return self._json(200,self.core.voice.interrupt(sid,owner_user_id='user').to_dict())
                if action=='close':return self._json(200,self.core.voice.close(sid,owner_user_id='user').to_dict())
            if u.path=='/api/os/tasks':
                self._scope(device,'task_status');return self._json(201,self.core.create_manual_task(body.get('title',''),priority=body.get('priority',5),deadline=body.get('deadline'),metadata=body.get('metadata') or {},owner_user_id='user'))
            if u.path=='/api/os/goals':
                self._scope(device,'conversation');return self._json(201,self.core.create_manual_goal(body.get('title',''),description=body.get('description',''),priority=body.get('priority',5),deadline=body.get('deadline'),owner_user_id='user'))
            if u.path=='/api/os/learning':
                self._scope(device,'conversation');return self._json(201,self.core.create_manual_learning(body.get('subject',''),body.get('objective',''),body.get('units') or [],owner_user_id='user'))
            if u.path=='/api/os/records':
                self._scope(device,'conversation');return self._json(201,self.core.save_manual_record(body.get('record_type',''),body.get('title',''),description=body.get('description',''),status=body.get('status','ACTIVE'),metadata=body.get('metadata') or {},owner_user_id='user'))
            if u.path=='/api/os/plan':
                self._scope(device,'task_status');return self._json(200,self.core.plan_os_item(str(body.get('record_type','')),str(body.get('record_id','')),owner_user_id='user'))
            if u.path.startswith('/api/os/goals/'):
                parts=[x for x in u.path.split('/') if x];self._scope(device,'conversation')
                if len(parts)==5 and parts[4]=='delete':return self._json(200,self.core.delete_goal(parts[3],owner_user_id='user'))
                if len(parts)==4:return self._json(200,self.core.update_manual_goal(parts[3],body,owner_user_id='user'))
                return self._json(404,{'error':'not_found'})
            if u.path.startswith('/api/os/tasks/'):
                parts=[x for x in u.path.split('/') if x];self._scope(device,'task_status')
                if len(parts)==5 and parts[4]=='delete':return self._json(200,self.core.delete_task(parts[3],owner_user_id='user'))
                if len(parts)==4:return self._json(200,self.core.update_manual_task(parts[3],body,owner_user_id='user'))
                return self._json(404,{'error':'not_found'})
            if u.path.startswith('/api/os/records/'):
                parts=[x for x in u.path.split('/') if x]
                self._scope(device,'conversation')
                if len(parts)==5 and parts[4]=='delete':return self._json(200,self.core.delete_manual_record(parts[3],owner_user_id='user'))
                if len(parts)==4:return self._json(200,self.core.update_manual_record(parts[3],body,owner_user_id='user'))
                return self._json(404,{'error':'not_found'})
            if u.path=='/api/conversation/models':
                self._scope(device,'conversation');return self._json(200,self.core.conversations.model_inventory())
            if u.path=='/api/conversation/model':
                self._scope(device,'conversation');return self._json(200,self.core.conversations.set_model(body.get('model_id','auto')))
            if u.path=='/api/conversation/agent':
                self._scope(device,'conversation');return self._json(200,self.core.agent_select(body.get('agent_id','personal'),owner_user_id='user'))
            if u.path=='/api/conversation/edit':
                self._scope(device,'conversation');sid=str(body.get('session_id') or '');mid=str(body.get('message_id') or '');s=self.core.conversations.ensure_session(sid);messages=self.core.conversations.messages(sid,200);target=next((x for x in messages if x.get('message_id')==mid and x.get('role')=='user'),None)
                if target is None:raise ValueError('conversation_message_not_found')
                self.core.store.delete_conversation_after(sid,mid)
                return self._json(200,self.core.conversations.send(body.get('text',''),session_id=sid,device_id=device['device_id'],model_id=body.get('model_id')))
            if u.path=='/api/conversation/retry':
                self._scope(device,'conversation');sid=str(body.get('session_id') or '');mid=str(body.get('message_id') or '');messages=self.core.conversations.messages(sid,200);target=next((x for x in reversed(messages) if x.get('role')=='user' and (not mid or x.get('message_id')==mid)),None)
                if target is None:raise ValueError('conversation_retry_message_not_found')
                self.core.store.delete_conversation_after(sid,target['message_id'])
                return self._json(200,self.core.conversations.send(target.get('text',''),session_id=sid,device_id=device['device_id'],model_id=body.get('model_id')))
            if u.path=='/api/chat':
                self._scope(device,'conversation')
                target_ref=body.get('target_device_id')
                target=None
                if target_ref:target=self.core.resolve_device_agent_target(target_ref)
                return self._json(200,self.core.conversations.send(body.get('text',''),session_id=body.get('session_id'),device_id=device['device_id'],target_device_id=(target or {}).get('device_id'),target_device_kind=(target or {}).get('kind'),model_id=body.get('model_id'),agent_id=body.get('agent_id')))
            if u.path=='/api/multimodal':
                self._scope(device,'conversation');value=self.core.multimodal_send(modality=body.get('modality',''),mime_type=body.get('mime_type'),data_base64=body.get('data_base64',''),prompt=body.get('prompt',''),session_id=body.get('session_id'),device_id=device['device_id']);return self._json(200 if value.get('status')=='COMPLETED' else 409,value)
            if u.path=='/api/background':
                self._scope(device,'task_status');goal_id=str(body.get('goal_id',''));self._owned_goal(goal_id);task=self.core.background.create(goal_id,max_iterations=int(body.get('max_iterations',100)),time_budget_seconds=float(body.get('time_budget_seconds',300)));return self._json(201,task.to_dict())
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
                self._scope(device,'task_status');self._owned_goal(self.core.store.load_background_task(parts[2]).goal_id);fn=getattr(self.core.background,parts[3]);return self._json(200,fn(parts[2]).to_dict())
            if len(parts)==4 and parts[:2]==['api','memory'] and parts[3] in {'approve','reject','reconcile'}:
                self._scope(device,'conversation');self._scope(device,'approvals')
                return self._json(200,self.core.inspector.memory_decision(parts[2],parts[3],actor='device:'+device['device_id']))
            if len(parts)==4 and parts[:2]==['api','tasks'] and parts[3] in {'pause','resume','cancel','replan','retry'}:
                self._scope(device,'task_status')
                return self._json(200,self.core.inspector.control(parts[2],parts[3]))
            if len(parts)==4 and parts[:2]==['api','tasks'] and parts[3]=='delete':
                self._scope(device,'task_status');return self._json(200,self.core.delete_task(parts[2],owner_user_id='user'))
            if len(parts)==4 and parts[:2]==['api','goals'] and parts[3]=='delete':
                self._scope(device,'conversation');return self._json(200,self.core.delete_goal(parts[2],owner_user_id='user'))
            if len(parts)==4 and parts[:2]==['api','sessions'] and parts[3]=='delete':
                self._scope(device,'conversation');return self._json(200,self.core.delete_conversation(parts[2],owner_user_id='user'))
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
