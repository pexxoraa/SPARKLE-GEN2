from __future__ import annotations
import hashlib,re
from dataclasses import asdict,dataclass
from typing import Any
from urllib.parse import urlsplit
from .gen1_interactions import Gen1BrowserSession

MAX_URL_CHARS=2048
MAX_TEXT_CHARS=10000
MAX_LINKS=25
MAX_TITLE_CHARS=512
MAX_TIMEOUT_SECONDS=30
MAX_INTERACTIONS=10
MAX_HISTORY_URLS=20
MAX_SCREENSHOT_BYTES=1_000_000
URL_RE=re.compile(r'https://[^\s<>"\'\]\[(){}]{1,2040}')

class BrowserOrchestrationError(RuntimeError):
    def __init__(self,category:str,message:str):super().__init__(message);self.category=category

@dataclass(frozen=True,slots=True)
class BrowserLinkSummary:
    url:str;host:str;label:str
    def to_dict(self):return asdict(self)
@dataclass(frozen=True,slots=True)
class BrowserScreenshotReference:
    reference:str;sha256:str;size_bytes:int
    def __post_init__(self):
        if not isinstance(self.reference,str) or not 1<=len(self.reference)<=2048:raise ValueError('invalid screenshot reference')
        if not isinstance(self.sha256,str) or not re.fullmatch(r'[0-9a-f]{64}',self.sha256):raise ValueError('invalid screenshot digest')
        if isinstance(self.size_bytes,bool) or not isinstance(self.size_bytes,int) or not 1<=self.size_bytes<=MAX_SCREENSHOT_BYTES:raise ValueError('invalid screenshot size')
    def to_dict(self):return asdict(self)
@dataclass(frozen=True,slots=True)
class BrowserPageObservation:
    final_url:str;title:str;visible_text:str;status_code:int;links:tuple[BrowserLinkSummary,...];session_reference:str;screenshot:BrowserScreenshotReference|None=None
    def to_dict(self):return {'final_url':self.final_url,'title':self.title,'visible_text':self.visible_text,'status_code':self.status_code,'links':[x.to_dict() for x in self.links],'session_reference':self.session_reference,'screenshot':None if self.screenshot is None else self.screenshot.to_dict()}
@dataclass(frozen=True,slots=True)
class BrowserNavigationResult:
    observation:BrowserPageObservation;requested_url:str
    def to_dict(self):return {'requested_url':self.requested_url,'observation':self.observation.to_dict()}
@dataclass(frozen=True,slots=True)
class BrowserInteractionResult:
    action:str;observation:BrowserPageObservation;changed:bool
    def to_dict(self):return {'action':self.action,'observation':self.observation.to_dict(),'changed':self.changed}

class BrowserOrchestrator:
    provider='SPARKLE Gen-1 BrowserSession'
    def __init__(self,gen1,*,owner_user_id='user'):
        self.gen1=getattr(gen1,'base',gen1);self.owner_user_id=owner_user_id;self._session=None;self._allowed_host=None;self._last=None;self._urls=[];self._cursor=-1;self._interactions=0
    @staticmethod
    def _normalize_url(raw):
        if not isinstance(raw,str) or not raw.strip() or len(raw)>MAX_URL_CHARS:raise ValueError('browser URL is invalid')
        value=raw.strip()
        if '://' not in value:value='https://'+value
        try:p=urlsplit(value);port=p.port
        except ValueError as exc:raise ValueError('browser URL is malformed') from exc
        if p.scheme!='https' or not p.hostname or p.username is not None or p.password is not None or port not in {None,443}:raise ValueError('browser requires credential-free HTTPS on port 443')
        return value,p.hostname.lower()
    @staticmethod
    def _session_ref(session_id):return 'browser-session:'+hashlib.sha256(str(session_id).encode()).hexdigest()[:32]
    @staticmethod
    def _links(text,allowed_host):
        out=[];seen=set()
        for raw in URL_RE.findall(text or ''):
            url=raw.rstrip('.,;:!?')
            try:p=urlsplit(url)
            except ValueError:continue
            if p.scheme!='https' or not p.hostname or p.hostname.lower()!=allowed_host or url in seen:continue
            seen.add(url);out.append(BrowserLinkSummary(url,p.hostname.lower(),url[:160]))
            if len(out)>=MAX_LINKS:break
        return tuple(out)
    def configured(self):
        svc=getattr(getattr(self.gen1,'system',None),'interactions',None)
        if svc is None:return False
        try:s=svc.status();return s.get('browser')=='configured' and s.get('browser_accepted') is True and s.get('live_browser_verified') is True
        except Exception:return False
    def authorize(self):
        if not self.configured():raise BrowserOrchestrationError('BROWSER_UNAVAILABLE','approved Gen-1 browser boundary is unavailable')
        svc=self.gen1.system.interactions;a=svc.browser_acceptance()
        if not isinstance(a,dict) or a.get('verified') is not True:raise BrowserOrchestrationError('BROWSER_UNAVAILABLE','Gen-1 browser acceptance is not verified')
        return {'authorization_reference':'gen1-browser-acceptance:'+str(a.get('record_id','verified')),'granted_scopes':['browser.navigate','browser.read','browser.interact']}
    def health(self):
        ok=self.configured();return {'ok':ok,'status':'HEALTHY' if ok else 'UNAVAILABLE','authorization_state':'AUTHORIZED' if ok else 'REQUIRED','provider':self.provider,'active_session':self._session is not None and not self._session.closed,'allowed_host':self._allowed_host,'interaction_count':self._interactions}
    def _ensure_session(self,url):
        normalized,host=self._normalize_url(url)
        if self._session is None:
            self._session=Gen1BrowserSession(self.gen1,[host],ttl_seconds=900);self._allowed_host=host
        elif host!=self._allowed_host:raise PermissionError('browser_host_not_allowlisted_for_session')
        return normalized
    def _observation(self,result):
        if not isinstance(result,dict):raise BrowserOrchestrationError('MALFORMED_RESPONSE','browser result is malformed')
        url=result.get('final_url');title=result.get('title','');text=result.get('text','');status=result.get('status_code')
        normalized,host=self._normalize_url(url)
        if host!=self._allowed_host:raise BrowserOrchestrationError('VERIFICATION_FAILURE','browser escaped allowed host')
        if not isinstance(title,str) or len(title)>MAX_TITLE_CHARS or not isinstance(text,str) or len(text)>MAX_TEXT_CHARS or isinstance(status,bool) or not isinstance(status,int) or not 100<=status<=599:raise BrowserOrchestrationError('MALFORMED_RESPONSE','browser observation exceeds bounds')
        return BrowserPageObservation(normalized,title,text,status,self._links(text,self._allowed_host),self._session_ref(self._session.session['id']))
    def _browse(self,url,timeout_seconds=15,*,record_history=True):
        if isinstance(timeout_seconds,bool) or not isinstance(timeout_seconds,int) or not 1<=timeout_seconds<=MAX_TIMEOUT_SECONDS:raise ValueError('browser timeout must be 1..30 seconds')
        normalized=self._ensure_session(url)
        try:raw=self._session.browse(normalized,timeout_seconds=timeout_seconds,max_text_chars=MAX_TEXT_CHARS)
        except TimeoutError as exc:raise BrowserOrchestrationError('TIMEOUT','browser navigation timed out') from exc
        except Exception as exc:
            text=str(exc).lower();category='TIMEOUT' if 'timeout' in text or 'timed out' in text else 'BROWSER_FAILURE';raise BrowserOrchestrationError(category,'browser navigation failed') from exc
        obs=self._observation(raw);self._last=obs
        if record_history:
            self._urls=self._urls[:self._cursor+1];self._urls.append(obs.final_url);self._urls=self._urls[-MAX_HISTORY_URLS:];self._cursor=len(self._urls)-1
        return obs
    def invoke_with_context(self,operation,payload,*,owner_user_id=None,**_context):
        if owner_user_id!=self.owner_user_id:raise PermissionError('browser_owner_mismatch')
        p=dict(payload or {})
        if operation=='navigate':
            if set(p)-{'url','timeout_seconds'}:raise ValueError('unsupported browser navigation argument')
            url=p.get('url');obs=self._browse(url,p.get('timeout_seconds',15));return {'provider':self.provider,'operation':operation,'result':BrowserNavigationResult(obs,str(url)).to_dict(),'provider_reference':obs.session_reference}
        if operation=='read':
            if p:raise ValueError('browser.read accepts no arguments')
            if self._last is None:raise BrowserOrchestrationError('NO_PAGE','browser session has no page observation')
            return {'provider':self.provider,'operation':operation,'result':self._last.to_dict(),'provider_reference':self._last.session_reference}
        if operation=='interact':
            if set(p)-{'action','target_url','timeout_seconds'}:raise ValueError('unsupported browser interaction argument')
            if self._last is None:raise BrowserOrchestrationError('NO_PAGE','browser session has no page observation')
            if self._interactions>=MAX_INTERACTIONS:raise BrowserOrchestrationError('INTERACTION_LIMIT','browser interaction limit reached')
            action=p.get('action');before=self._last.final_url
            if action=='open_link':
                target,_=self._normalize_url(p.get('target_url'));allowed={x.url for x in self._last.links}
                if target not in allowed:raise PermissionError('browser_interaction_target_not_observed')
                obs=self._browse(target,p.get('timeout_seconds',15))
            elif action=='reload':obs=self._browse(before,p.get('timeout_seconds',15),record_history=False)
            elif action=='back':
                if self._cursor<=0:raise BrowserOrchestrationError('NO_HISTORY','browser has no previous page')
                self._cursor-=1;obs=self._browse(self._urls[self._cursor],p.get('timeout_seconds',15),record_history=False)
            elif action=='forward':
                if self._cursor<0 or self._cursor>=len(self._urls)-1:raise BrowserOrchestrationError('NO_HISTORY','browser has no forward page')
                self._cursor+=1;obs=self._browse(self._urls[self._cursor],p.get('timeout_seconds',15),record_history=False)
            else:raise PermissionError('browser_interaction_not_allowlisted')
            self._interactions+=1;return {'provider':self.provider,'operation':operation,'result':BrowserInteractionResult(str(action),obs,obs.final_url!=before or action=='reload').to_dict(),'provider_reference':obs.session_reference}
        raise KeyError(operation)
    def invoke(self,operation,payload):return self.invoke_with_context(operation,payload,owner_user_id=self.owner_user_id)
    def verify(self,operation,result):
        if not isinstance(result,dict) or result.get('provider')!=self.provider or result.get('operation')!=operation:return {'verified':False,'reason':'provider_or_operation_mismatch','method':'Gen-1 browser history reread'}
        if self._session is None:return {'verified':False,'reason':'no_active_browser_session','method':'Gen-1 browser history reread'}
        base=self._session.verify_last()
        if base.get('verified') is not True:return {'verified':False,'reason':'gen1_history_verification_failed','method':'Gen-1 browser history reread'}
        try:
            history=self._session.service.history(self._session.session['id'],limit=1);event=history[0];persisted=event.get('result',{});obs=(result.get('result') or {}).get('observation') if operation=='navigate' else (result.get('result') or {})
            if operation=='interact':obs=(result.get('result') or {}).get('observation')
            if not isinstance(obs,dict):return {'verified':False,'reason':'observation_missing','method':'Gen-1 browser history reread'}
            final=obs.get('final_url');_,host=self._normalize_url(final)
            if host!=self._allowed_host:return {'verified':False,'reason':'host_mismatch','method':'Gen-1 browser history reread'}
            if operation=='read':
                # Read is verified against the persisted last navigation event without executing another network request.
                if persisted.get('final_url')!=final or persisted.get('title')!=obs.get('title') or persisted.get('status_code')!=obs.get('status_code'):return {'verified':False,'reason':'read_observation_mismatch','method':'Gen-1 persisted interaction history'}
            else:
                if persisted.get('final_url')!=final or persisted.get('status_code')!=obs.get('status_code'):return {'verified':False,'reason':'navigation_state_mismatch','method':'Gen-1 persisted interaction history'}
            digest=hashlib.sha256((str(final)+'\0'+str(obs.get('title',''))+'\0'+str(obs.get('status_code'))).encode()).hexdigest()
            return {'verified':True,'method':'Gen-1 persisted revisioned browser interaction history','provider':self.provider,'session_reference':self._session_ref(self._session.session['id']),'event_id':event.get('id'),'final_url_sha256':hashlib.sha256(str(final).encode()).hexdigest(),'observation_sha256':digest,'allowed_host':self._allowed_host}
        except Exception:return {'verified':False,'reason':'browser_verification_error','method':'Gen-1 persisted interaction history'}
    def verify_with_context(self,operation,result,*,owner_user_id=None,**_context):
        if owner_user_id!=self.owner_user_id:return {'verified':False,'reason':'browser_owner_mismatch','method':'owner-bound browser session'}
        return self.verify(operation,result)
    def close(self):
        if self._session is None:return {'status':'not_started'}
        state=self._session.close();self._session=None;self._last=None;self._allowed_host=None;self._urls=[];self._cursor=-1;return {'status':state.get('status'),'revision':state.get('revision')}
