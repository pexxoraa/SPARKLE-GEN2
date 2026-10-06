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

class PersonalCore:
    def __init__(self,components=None):
        self.store,self.agent,self.sessions=components or build_components(activate_external_connectors=True);self.devices=DeviceIdentityService(self.store);self.router=DeviceRouter(self.devices);self.notifications=getattr(self.agent,'notifications',None) or NotificationIntelligenceService(self.store);self.delivery=getattr(self.notifications,'delivery',None);self.conversations=ConversationService(self.store,self.sessions,self.agent);self.voice=VoiceSessionService(self.store,model_manager=getattr(self.agent.gen1,'model_manager',None),conversation_service=self.conversations);self.multimodal=MultimodalGateway();self.background=BackgroundTaskService(self.store,lambda:self.agent,notifier=self.notifications);self.autonomy=AutonomyController(self.store);self.operations=self.agent.operations
    @staticmethod
    def _voice_payload(response):
        value=response.to_dict(include_audio=False)
        value['audio_chunks']=[x.metadata()|{'audio_base64':base64.b64encode(bytes(x.audio)).decode('ascii')} for x in response.audio_chunks]
        return value
    def device_agent_targets(self,*,owner_user_id='user'):
        targets=[]
        for cid,adapter in getattr(self.agent.connectors,'_adapters',{}).items():
            if cid not in {'computer','linux','mobile'}:continue
            try:
                health=adapter.health()
                bound=getattr(adapter,'bound_device_id',None)
                if health.get('status') in {'HEALTHY','CONNECTED'} and bound:
                    targets.append({'target_id':f'{cid}:{bound}','device_id':bound,'name':'This PC' if cid in {'computer','linux'} else 'Mobile device','kind':cid,'status':health.get('status'),'capabilities':list(getattr(adapter,'_capabilities',[]) or []) or ({'computer':['computer.read','computer.act'],'linux':['linux.inspect','linux.execute'],'mobile':['mobile.read','mobile.act']}.get(cid,[]))})
            except Exception:pass
        # Only expose authenticated mobile endpoints when a live connector exists.
        # Listing an online identity without a transport made Device Agent appear usable
        # while every command failed at execution time.
        seen=set()
        return [x for x in targets if x.get('target_id') and not (x['target_id'] in seen or seen.add(x['target_id']))]

    def resolve_device_agent_target(self,target_ref):
        value=str(target_ref or '').strip()
        for target in self.device_agent_targets(owner_user_id='user'):
            if target.get('target_id')==value:
                return dict(target)
        raise PermissionError('invalid_device_agent_target')
    def agent_catalog(self,*,conversation_only=False):
        return self.agent.agent_registry.list(conversation_only=bool(conversation_only))

    def agent_select(self,agent_id,*,owner_user_id='user'):
        profile=self.agent.agent_registry.resolve(agent_id)
        self.store.save_setting('conversation_agent',{'agent_id':profile.agent_id,'owner_user_id':owner_user_id})
        return {'selected':profile.to_dict(),'agents':self.agent.agent_registry.list(conversation_only=True)}

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
    def os_snapshot(self,*,owner_user_id='user'):
        all_goals=[g for g in self.store.recent_goals(200) if g.get('user_id','user')==owner_user_id]
        manual_projects=self.store.os_records(owner_user_id=owner_user_id,record_type='project',limit=50)
        manual_research=self.store.os_records(owner_user_id=owner_user_id,record_type='research',limit=50)
        manual_skills=self.store.os_records(owner_user_id=owner_user_id,record_type='skill',limit=100)
        task_goals=[g for g in all_goals if 'task_capture' in set(g.get('constraints') or []) and not ConversationService._looks_like_accidental_task_capture(str(g.get('normalized_objective') or g.get('user_request') or ''))]
        goals=[g for g in all_goals if self._visible_operational_goal(g) and 'task_capture' not in set(g.get('constraints') or [])]
        task_goal_ids={g.get('goal_id') for g in task_goals}
        runs=[r for r in self.store.all_task_runs(100) if r.get('goal_id') in task_goal_ids]
        goal_map={g.get('goal_id'):g for g in task_goals}
        tasks=[]
        for r in runs:
            g=goal_map.get(r.get('goal_id'),{});captured=r.get('status')=='CAPTURED' or any(isinstance(x,dict) and x.get('type')=='task_capture' for x in r.get('events',[]));total=len(r.get('completed_steps',[]))+len(r.get('pending_steps',[]))+len(r.get('failed_steps',[]));tasks.append({'task_run_id':r.get('task_run_id'),'goal_id':r.get('goal_id'),'title':str(g.get('normalized_objective') or g.get('user_request',''))[:240],'status':g.get('status',r.get('status')),'run_status':r.get('status'),'progress':100 if r.get('status')=='COMPLETED' else round(100*len(r.get('completed_steps',[]))/max(1,total)),'current_operation':r.get('current_step'),'updated_at':r.get('updated_at'),'task_capture':captured,'priority':g.get('priority',5),'deadline':g.get('deadline'),'metadata':dict(g.get('metadata') or {})})
        learning=self.agent.learning
        plans=[] if learning is None else [x.to_dict() if hasattr(x,'to_dict') else dict(x) for x in learning.list(owner_user_id=owner_user_id,limit=50)]
        experiments=self.store.experiments()
        project_ids=list(dict.fromkeys([x.get('record_id') for x in manual_projects]+[x.get('project_id') for x in experiments if x.get('project_id')]))
        research=manual_research+[x for x in experiments if x.get('research_id') or x.get('project_id')]
        skills=list(manual_skills)
        for p in plans:
            for u in p.get('units',[]):
                skills.append({'skill_id':u.get('unit_id'),'name':u.get('title'),'status':u.get('status'),'best_score':u.get('best_score'),'plan_id':p.get('plan_id'),'subject':p.get('subject')})
        progress={'goals_total':len(goals),'goals_completed':sum(g.get('status')=='COMPLETED' for g in goals),'tasks_total':len(tasks),'tasks_completed':sum(t.get('run_status')=='COMPLETED' for t in tasks),'learning_plans':len(plans),'skills_tracked':len(skills),'research_records':len(research),'generated_at':now()}
        settings={'autonomy':self.autonomy.get(),'voice':self.voice.health()}
        projects=[dict(x) for x in manual_projects]
        for x in project_ids:
            if x in {p.get('record_id') for p in projects}:continue
            projects.append({'record_id':x,'project_id':x,'owner_user_id':owner_user_id,'record_type':'project','title':x,'experiment_count':sum(e.get('project_id')==x for e in experiments),'status':'PERSISTED'})
        for x in projects:
            x.setdefault('experiment_count',sum(e.get('project_id')==x.get('record_id',x.get('project_id')) for e in experiments))
        graph_nodes=[{'id':g.get('goal_id'),'type':'goal','title':g.get('normalized_objective'),'status':g.get('status')} for g in goals]
        graph_edges=[]
        for t in tasks:
            if t.get('goal_id'):graph_nodes.append({'id':t['goal_id'],'type':'task','title':t.get('title'),'status':t.get('status')});graph_edges.append({'from':t['goal_id'],'to':t['goal_id'],'type':'execution'})
        for p in projects:
            graph_nodes.append({'id':p.get('record_id'),'type':'project','title':p.get('title'),'status':p.get('status')});rel=p.get('goal_id') or (p.get('metadata') or {}).get('goal_id')
            if rel:graph_edges.append({'from':p.get('record_id'),'to':rel,'type':'supports'})
        for r in research:
            rid=r.get('record_id') or r.get('research_id');graph_nodes.append({'id':rid,'type':'research','title':r.get('title') or r.get('topic'),'status':r.get('status') or r.get('verification_state')});rel=r.get('project_id') or (r.get('metadata') or {}).get('project_id')
            if rid and rel:graph_edges.append({'from':rid,'to':rel,'type':'part_of'})
        for sk in manual_skills:
            sid=sk.get('record_id');graph_nodes.append({'id':sid,'type':'skill','title':sk.get('title') or sk.get('name'),'status':sk.get('status')});rel=sk.get('learning_plan_id') or (sk.get('metadata') or {}).get('learning_plan_id')
            if sid and rel:graph_edges.append({'from':sid,'to':rel,'type':'developed_by'})
            rel=sk.get('project_id') or (sk.get('metadata') or {}).get('project_id')
            if sid and rel:graph_edges.append({'from':sid,'to':rel,'type':'applied_in'})
        graph={'nodes':graph_nodes[:300],'edges':graph_edges[:500]}
        return {'goals':goals[:50],'tasks':tasks[:100],'learning_plans':plans[:50],'skills':skills[:100],'projects':projects[:50],'research':research[:50],'progress':progress,'settings':settings,'graph':graph}
    @staticmethod
    def _os_text(value,field,limit=500):
        if not isinstance(value,str) or not value.strip():raise ValueError(f'{field} is required')
        value=' '.join(value.strip().split())
        if len(value)>limit:raise ValueError(f'{field} exceeds bound')
        return value

    def create_manual_task(self,title,*,priority=5,deadline=None,metadata=None,owner_user_id='user'):
        from ...application.conversation import ConversationService
        title=self._os_text(title,'task title',500)
        result=self.conversations._capture_task('Add a new task '+title)
        if not result:raise ValueError('task title is invalid')
        goal=self.store.load_goal(result['goal_id'])
        try:priority=max(1,min(10,int(priority)))
        except (TypeError,ValueError):priority=5
        goal.priority=priority;goal.deadline=(str(deadline).strip() or None) if deadline is not None else None
        goal.metadata=dict(metadata or {})
        goal.updated_at=now();self.store.save_goal(goal)
        return self.task_view_for_goal(goal.goal_id)

    def update_manual_goal(self,goal_id,fields,*,owner_user_id='user'):
        goal=self.store.load_goal(goal_id)
        if goal.user_id!=owner_user_id:raise PermissionError('goal_owner_mismatch')
        fields=dict(fields or {})
        if 'title' in fields and str(fields['title']).strip():
            title=self._os_text(str(fields['title']),'goal title',300)
            goal.normalized_objective=title
            goal.user_request='Create a goal: '+title
        if 'description' in fields:
            desc=' '.join(str(fields.get('description') or '').strip().split())[:600]
            goal.user_request=(f'Create a goal: {goal.normalized_objective}' + (f' — {desc}' if desc else ''))[:12000]
        if 'priority' in fields:
            try:goal.priority=max(1,min(10,int(fields['priority'])))
            except (TypeError,ValueError):raise ValueError('priority must be 1..10')
        if 'deadline' in fields:goal.deadline=str(fields.get('deadline') or '').strip() or None
        if 'success_criteria' in fields:
            criteria=fields.get('success_criteria') or []
            if not isinstance(criteria,list) or len(criteria)>20:raise ValueError('success_criteria must contain at most 20 items')
            goal.success_criteria=[self._os_text(str(x),'success criterion',300) for x in criteria if str(x).strip()]
        if 'metadata' in fields and isinstance(fields['metadata'],dict):
            goal.metadata=dict(goal.metadata or {})|dict(fields['metadata'])
        goal.updated_at=now();self.store.save_goal(goal)
        self.store.event(goal.goal_id,'goal_updated',{'source':'manual_os_ui','fields':sorted(fields.keys())},goal.updated_at)
        return goal.to_dict()

    def update_manual_task(self,goal_id,fields,*,owner_user_id='user'):
        goal=self.store.load_goal(goal_id)
        if goal.user_id!=owner_user_id:raise PermissionError('task_owner_mismatch')
        if 'task_capture' not in set(goal.constraints or []):raise ValueError('not_a_manual_task')
        return self.update_manual_goal(goal_id,fields,owner_user_id=owner_user_id)

    def task_view_for_goal(self,goal_id):
        return next((x for x in self.task_view() if x.get('goal_id')==goal_id), {'goal_id':goal_id,'status':'WAITING'})

    def create_manual_goal(self,title,*,description='',priority=5,deadline=None,owner_user_id='user'):
        import uuid
        title=self._os_text(title,'goal title',300)
        description=' '.join(str(description or '').strip().split())[:600]
        try:priority=max(1,min(10,int(priority)))
        except (TypeError,ValueError):priority=5
        stamp=now();request='Create a goal: '+title
        if description:request+=' — '+description
        goal=Goal(uuid.uuid4().hex,request,title,constraints=['goal_capture','manual_entry'],priority=priority,deadline=(str(deadline).strip() or None) if deadline is not None else None,success_criteria=['Goal remains explicitly saved in Personal Goals'],status=GoalStatus.CREATED,created_at=stamp,updated_at=stamp,user_id=owner_user_id)
        self.store.save_goal(goal);self.store.event(goal.goal_id,'goal_captured',{'source':'manual_os_ui','user_id':owner_user_id},stamp)
        return {'status':'COMPLETED','goal':goal.to_dict(),'goal_id':goal.goal_id,'text':f'Added goal: {title}.','verified':['goal persisted']}

    def create_manual_learning(self,subject,objective,units,*,owner_user_id='user'):
        if self.agent.learning is None:raise RuntimeError('learning_unavailable')
        clean_units=[self._os_text(x,'learning unit',180) for x in units if isinstance(x,str) and x.strip()]
        return {'status':'COMPLETED','plan':self.agent.learning.create(owner_user_id=owner_user_id,subject=self._os_text(subject,'subject',160),objective=self._os_text(objective,'objective',500),units=clean_units).to_dict(),'text':'Learning plan created and persisted.'}

    def save_manual_record(self,record_type,title,*,description='',status='ACTIVE',metadata=None,owner_user_id='user'):
        import uuid
        rtype=str(record_type).strip().lower()
        if rtype not in {'project','research','skill'}:raise ValueError('unsupported_os_record_type')
        title=self._os_text(title,'title',300);description=' '.join(str(description or '').strip().split())[:1000]
        stamp=now();rid=rtype+'_'+uuid.uuid4().hex
        payload={'record_id':rid,'owner_user_id':owner_user_id,'record_type':rtype,'title':title,'name':title,'description':description,'status':str(status or 'ACTIVE').upper(),'created_at':stamp,'updated_at':stamp,'metadata':dict(metadata or {})}
        self.store.save_os_record(payload)
        return payload

    def update_manual_record(self,record_id,fields,*,owner_user_id='user'):
        row=self.store.load_os_record(record_id)
        if row.get('owner_user_id')!=owner_user_id:raise PermissionError('os_record_owner_mismatch')
        allowed={'title','name','description','status','metadata','goal_id','project_id','learning_plan_id','unit_id','question','hypothesis','method','level'}
        for key,value in dict(fields or {}).items():
            if key not in allowed:continue
            if key in {'title','name','description','question','hypothesis','method','goal_id','project_id','learning_plan_id','unit_id','level'} and value is not None:
                row[key]=str(value).strip()[:1000]
            elif key=='status':row[key]=str(value).upper()[:80]
            elif key=='metadata' and isinstance(value,dict):row[key]=dict(value)
        row['updated_at']=now();self.store.save_os_record(row);return row

    def delete_manual_record(self,record_id,*,owner_user_id='user'):
        self.store.delete_os_record(record_id,owner_user_id=owner_user_id)
        return {'status':'DELETED','record_id':record_id}

    def plan_os_item(self,record_type,record_id,*,owner_user_id='user'):
        row=None
        if record_type in {'project','research','skill'}:row=self.store.load_os_record(record_id)
        elif record_type=='goal':row=self.store.load_goal(record_id).to_dict()
        elif record_type=='task':
            row=next((x for x in self.task_view() if x.get('goal_id')==record_id),None)
        elif record_type=='learning':
            row=self.store.load_learning_plan(record_id).to_dict()
        if row is None:raise KeyError(record_id)
        if row.get('owner_user_id','user')!=owner_user_id and record_type not in {'goal','task'}:raise PermissionError('os_item_owner_mismatch')
        title=str(row.get('title') or row.get('name') or row.get('subject') or row.get('objective') or row.get('goal') or record_id)
        context=str(row.get('description') or row.get('question') or row.get('hypothesis') or row.get('objective') or '')
        command='Create a goal for '+title+' and plan it carefully.'
        if context:command+=' Context: '+context[:700]
        result=self.agent.start(command,user_id=owner_user_id)
        if record_type in {'project','research','skill'}:
            row=self.update_manual_record(record_id,{'goal_id':result.get('goal_id'),'status':'PLANNED'},owner_user_id=owner_user_id)
        return {'status':result.get('status'),'goal_id':result.get('goal_id'),'task_run_id':result.get('task_run_id'),'text':result.get('text'),'linked_record':row,'planning_result':result}

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
        if 'task_status' in scopes:
            goals=[g for g in self.store.recent_goals(200) if self._visible_operational_goal(g) and 'task_capture' not in set(g.get('constraints') or [])]
            task_goals=[g for g in self.store.recent_goals(200) if 'task_capture' in set(g.get('constraints') or []) and not ConversationService._looks_like_accidental_task_capture(str(g.get('normalized_objective') or g.get('user_request') or ''))]
            visible_ids={g.get('goal_id') for g in goals}|{g.get('goal_id') for g in task_goals}
            tasks=[r for r in self.store.all_task_runs(200) if r.get('goal_id') in {g.get('goal_id') for g in task_goals}]
            out.update({'goals':goals,'tasks':tasks,'background_tasks':[x.to_dict() for x in self.store.background_tasks()]})
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
    @staticmethod
    def _visible_operational_goal(goal):
        constraints=set(goal.get('constraints') or [])
        text=str(goal.get('user_request') or goal.get('normalized_objective') or '')
        if 'task_capture' in constraints:
            return not ConversationService._looks_like_accidental_task_capture(text)
        return ConversationService._looks_like_goal_request(text)

    def delete_goal(self,goal_id,*,owner_user_id='user'):
        goal=self.store.load_goal(goal_id)
        if goal.user_id!=owner_user_id:raise PermissionError('goal_owner_mismatch')
        self.store.delete_goal(goal_id)
        return {'status':'DELETED','goal_id':goal_id}

    def delete_task(self,goal_id,*,owner_user_id='user'):
        return self.delete_goal(goal_id,owner_user_id=owner_user_id)

    def delete_conversation(self,session_id,*,owner_user_id='user'):
        # Sessions are device-scoped in the current Core; messages contain no separate user field.
        self.store.load_session(session_id)
        self.store.delete_conversation_session(session_id)
        return {'status':'DELETED','session_id':session_id}

    def task_view(self):
        goals={g['goal_id']:g for g in self.store.recent_goals(200) if 'task_capture' in set(g.get('constraints') or []) and not ConversationService._looks_like_accidental_task_capture(str(g.get('normalized_objective') or g.get('user_request') or ''))};out=[]
        for run in self.store.all_task_runs(200):
            g=goals.get(run['goal_id'])
            if not g:continue
            captured=run.get('status')=='CAPTURED' or any(isinstance(x,dict) and x.get('type')=='task_capture' for x in run.get('events',[]));total=len(run.get('completed_steps',[]))+len(run.get('pending_steps',[]))+len(run.get('failed_steps',[]));progress=100 if run.get('status')=='COMPLETED' else round(100*len(run.get('completed_steps',[]))/max(1,total))
            out.append({'goal_id':run['goal_id'],'goal':g.get('normalized_objective') or g.get('user_request',''),'status':g.get('status',run.get('status')),'progress':progress,'current_operation':run.get('current_step'),'started':run.get('started_at'),'approvals':run.get('approvals',[]),'artifacts':run.get('artifacts',[]),'trace_id':run.get('trace_id'),'task_capture':captured,'priority':g.get('priority',5),'deadline':g.get('deadline'),'metadata':dict(g.get('metadata') or {})})
        return out

class Handler(BaseHTTPRequestHandler):
    server_version='SPARKLE-Personal-Core/1'
    def log_message(self,fmt,*args):pass
    @property
    def core(self):return self.server.core
    def _json(self,status,value,headers=None):
        return JsonResponder.send(self,status,value,headers)
    def _body(self,max_bytes=1_000_000):
        return JsonRequest.read(self,max_bytes)
    def _device_token(self):
        return DeviceAuthentication.token(self)
    def _device(self):return self.core.devices.authenticate(self._device_token())
    @staticmethod
    def _scope(device,scope):
        if scope not in set(device.get('capabilities',[])):raise PermissionError('device_scope_denied:'+scope)
    def _static(self,path):
        return StaticFileService(Path(__file__).with_name('web')).serve(self,path)
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
            if u.path=='/api/conversation/models':self._scope(device,'conversation');return self._json(200,self.core.conversations.model_inventory())
            if u.path=='/api/sessions':self._scope(device,'conversation');return self._json(200,{'sessions':self.core.conversations.session_summaries(100)})
            if u.path.startswith('/api/sessions/') and u.path.endswith('/context'):
                self._scope(device,'conversation');sid=u.path.split('/')[3];s=self.core.conversations.ensure_session(sid);messages=self.core.conversations.messages(sid,200);latest=next((str(x.get('text','')).strip() for x in reversed(messages) if x.get('role')=='user' and str(x.get('text','')).strip()),'');return self._json(200,{'context':self.core.conversations._conversation_context(s,latest)})
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
                if len(parts)==4 and parts[3]=='delete':return self._json(200,self.core.delete_goal(parts[2],owner_user_id='user'))
                if len(parts)==3:return self._json(200,self.core.update_manual_goal(parts[2],body,owner_user_id='user'))
                return self._json(404,{'error':'not_found'})
            if u.path.startswith('/api/os/tasks/'):
                parts=[x for x in u.path.split('/') if x];self._scope(device,'task_status')
                if len(parts)==4 and parts[3]=='delete':return self._json(200,self.core.delete_task(parts[2],owner_user_id='user'))
                if len(parts)==3:return self._json(200,self.core.update_manual_task(parts[2],body,owner_user_id='user'))
                return self._json(404,{'error':'not_found'})
            if u.path.startswith('/api/os/records/'):
                parts=[x for x in u.path.split('/') if x]
                self._scope(device,'conversation')
                if len(parts)==4 and parts[3]=='delete':return self._json(200,self.core.delete_manual_record(parts[2],owner_user_id='user'))
                if len(parts)==3:return self._json(200,self.core.update_manual_record(parts[2],body,owner_user_id='user'))
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
