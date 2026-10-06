from __future__ import annotations
import base64,binascii
from sparkle.content import ContentEnvelope,ContentPart
from sparkle.contracts import Message
from sparkle.model import ModelRequest
from sparkle_gen2.background import BackgroundTaskService
from sparkle_gen2.autonomy import AutonomyController
from sparkle_gen2.runtime import build_components
from sparkle_gen2.application.conversation import ConversationService
from sparkle_gen2.device_identity import DeviceIdentityService
from sparkle_gen2.device_routing import DeviceRouter
from sparkle_gen2.application.knowledge.multimodal import MultimodalGateway
from sparkle_gen2.notifications import NotificationIntelligenceService
from sparkle_gen2.voice_runtime import VoiceSessionService
from sparkle_gen2.core_time import now
from sparkle_gen2.domain.models import Goal, GoalStatus

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
        result=self.conversations._capture_task('Add a new task '+title,owner_user_id=owner_user_id)
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
