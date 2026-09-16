from __future__ import annotations

class Gen1BrowserSession:
    def __init__(self,gen1,allowed_hosts,*,ttl_seconds=900):
        service=getattr(getattr(gen1,'system',None),'interactions',None)
        if service is None:raise RuntimeError('external_dependency:gen1_interaction_service')
        self.service=service;self.session=service.start_session('browser',ttl_seconds=ttl_seconds,allowed_hosts=list(allowed_hosts));self.closed=False
    def browse(self,url,*,timeout_seconds=15,max_text_chars=20000):
        if self.closed:raise RuntimeError('interaction_session_closed')
        result=self.service.browse_session(self.session['id'],url,expected_revision=self.session['revision'],timeout_seconds=timeout_seconds,max_text_chars=max_text_chars);self.session=self.service.session(self.session['id']);return result
    def verify_last(self):
        history=self.service.history(self.session['id'],limit=1)
        if not history:return {'verified':False,'reason':'no_interaction_history'}
        event=history[0];result=event.get('result',{});return {'verified':event.get('event')=='browse' and isinstance(result.get('status_code'),int),'method':'Gen-1 persisted interaction history','event_id':event.get('id')}
    def close(self):
        if not self.closed:self.session=self.service.close_session(self.session['id'],expected_revision=self.session['revision']);self.closed=True
        return self.session

class Gen1ComputerSession:
    def __init__(self,gen1,allowed_actions,*,ttl_seconds=900):
        service=getattr(getattr(gen1,'system',None),'interactions',None)
        if service is None:raise RuntimeError('external_dependency:gen1_interaction_service')
        self.service=service;self.session=service.start_session('computer',ttl_seconds=ttl_seconds,allowed_actions=list(allowed_actions));self.closed=False
    def perform(self,action):
        if self.closed:raise RuntimeError('interaction_session_closed')
        result=self.service.perform_session(self.session['id'],dict(action),expected_revision=self.session['revision']);self.session=self.service.session(self.session['id']);return result
    def verify_last(self):
        history=self.service.history(self.session['id'],limit=1)
        if not history:return {'verified':False,'reason':'no_interaction_history'}
        event=history[0];result=event.get('result',{});return {'verified':event.get('event')=='computer_action' and result.get('completed') is True,'method':'Gen-1 persisted interaction history','event_id':event.get('id')}
    def close(self):
        if not self.closed:self.session=self.service.close_session(self.session['id'],expected_revision=self.session['revision']);self.closed=True
        return self.session
