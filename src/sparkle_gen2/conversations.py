from __future__ import annotations
import uuid
from .core_time import now

class ConversationService:
    def __init__(self,store,sessions,agent):self.store=store;self.sessions=sessions;self.agent=agent
    def ensure_session(self,session_id=None):
        if session_id:
            try:return self.sessions.recover(session_id)
            except KeyError:pass
        return self.sessions.create()
    def messages(self,session_id,limit=100):self.sessions.recover(session_id);return self.store.conversation_messages(session_id,limit)
    def _status(self,goal_id):
        goal=self.store.load_goal(goal_id);plan=self.store.load_plan(goal.plan_id);run=self.store.load_task_run_for_goal(goal_id);return self.agent.report(goal,plan,run)
    def _dispatch(self,s,text):
        active=s.active_goal_id;normalized=' '.join(text.lower().split())
        if active:
            status_prefixes=('how did it go','how is it going','what are you doing','what are you waiting for','show me what you are doing','show me what you’re doing','status')
            continue_prefixes=('continue','resume','keep working','run ','work on ','finish ','research ','prepare ','move ')
            if any(normalized.startswith(x) for x in status_prefixes):
                try:return self._status(active)
                except KeyError:pass
            if any(normalized.startswith(x) for x in continue_prefixes):
                fn=getattr(self.agent,'continue_goal',None)
                if callable(fn):return fn(active,text)
                fn=getattr(self.agent,'resume',None)
                if callable(fn):return fn(active)
        return self.agent.start(text)
    def send(self,text,*,session_id=None,device_id=None):
        if not isinstance(text,str) or not text.strip():raise ValueError('message_required')
        s=self.ensure_session(session_id);user={'message_id':uuid.uuid4().hex,'session_id':s.session_id,'role':'user','text':text.strip(),'created_at':now(),'device_id':device_id};self.store.save_conversation_message(user['message_id'],s.session_id,user)
        result=self._dispatch(s,text.strip());self.sessions.attach_goal(s.session_id,result['goal_id'])
        assistant={'message_id':uuid.uuid4().hex,'session_id':s.session_id,'role':'assistant','text':result['text'],'created_at':now(),'goal_id':result['goal_id'],'status':result['status'],'checked':list(result.get('checked',[])),'verified':list(result.get('verified',[])),'approvals':list(result.get('approvals',[]))};self.store.save_conversation_message(assistant['message_id'],s.session_id,assistant)
        return {'session_id':s.session_id,'message':assistant,'result':result}
    def record_external(self,user_text,assistant_text,*,session_id=None,device_id=None,metadata=None):
        s=self.ensure_session(session_id);user={'message_id':uuid.uuid4().hex,'session_id':s.session_id,'role':'user','text':str(user_text),'created_at':now(),'device_id':device_id,'metadata':dict(metadata or {})};self.store.save_conversation_message(user['message_id'],s.session_id,user)
        assistant={'message_id':uuid.uuid4().hex,'session_id':s.session_id,'role':'assistant','text':str(assistant_text),'created_at':now(),'status':'COMPLETED','metadata':dict(metadata or {})};self.store.save_conversation_message(assistant['message_id'],s.session_id,assistant);return {'session_id':s.session_id,'message':assistant}
