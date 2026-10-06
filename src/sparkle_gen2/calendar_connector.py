from __future__ import annotations
import hashlib,json,os,re,socket
from dataclasses import asdict,dataclass
from datetime import UTC,datetime,timedelta
from pathlib import Path
from typing import Any,Callable

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

CALENDAR_READONLY_SCOPE='https://www.googleapis.com/auth/calendar.readonly'
CALENDAR_SECRET_REF='SPARKLE_CALENDAR_TOKEN_FILE'
DEFAULT_CALENDAR_RESULTS=10
DEFAULT_EVENT_RESULTS=10
MAX_RESULTS=25
DEFAULT_WINDOW_DAYS=7
MAX_WINDOW_DAYS=366
MAX_SUMMARY_CHARS=512
MAX_ID_CHARS=1024
ID_RE=re.compile(r'^[^\x00-\x20\x7f]{1,1024}$')
STATUS_VALUES={'confirmed','tentative','cancelled'}
ACCESS_ROLES={'freeBusyReader','reader','writer','owner'}

class CalendarConnectorError(RuntimeError):
    def __init__(self,category:str,message:str):super().__init__(message);self.category=category

@dataclass(frozen=True,slots=True)
class CalendarSummary:
    calendar_id:str
    summary:str
    access_role:str|None
    primary:bool=False
    def to_dict(self):return asdict(self)

@dataclass(frozen=True,slots=True)
class CalendarList:
    calendars:tuple[CalendarSummary,...]
    result_count:int
    has_more:bool
    def to_dict(self):return {'calendars':[x.to_dict() for x in self.calendars],'result_count':self.result_count,'has_more':self.has_more}

@dataclass(frozen=True,slots=True)
class CalendarEventSummary:
    event_id:str
    calendar_id:str
    status:str
    summary:str
    start:dict[str,str]
    end:dict[str,str]
    all_day:bool
    def to_dict(self):return asdict(self)

@dataclass(frozen=True,slots=True)
class CalendarEventList:
    events:tuple[CalendarEventSummary,...]
    result_count:int
    has_more:bool
    time_min:str
    time_max:str
    def to_dict(self):return {'events':[x.to_dict() for x in self.events],'result_count':self.result_count,'has_more':self.has_more,'time_min':self.time_min,'time_max':self.time_max}

@dataclass(frozen=True,slots=True)
class CalendarEventDetails:
    event_id:str
    calendar_id:str
    status:str
    summary:str
    start:dict[str,str]
    end:dict[str,str]
    all_day:bool
    updated:str|None
    def to_dict(self):return asdict(self)

class CalendarCredentialSource:
    """Resolve a symbolic Calendar OAuth credential reference outside repository persistence."""
    def __init__(self,*,secret_ref=CALENDAR_SECRET_REF,path:Path|str|None=None,loader:Callable[...,Any]|None=None,request_factory:Callable[[],Any]|None=None):
        self.secret_ref=secret_ref;configured=os.environ.get(secret_ref);self._path=Path(path).expanduser() if path is not None else (Path(configured).expanduser() if configured else None);self._loader=loader or Credentials.from_authorized_user_file;self._request_factory=request_factory or Request
    def configured(self)->bool:
        if self._path is None:return False
        try:return self._path.is_file() and not self._path.is_symlink()
        except OSError:return False
    def load(self):
        if not self.configured():raise CalendarConnectorError('AUTH_REQUIRED','Calendar OAuth credential reference is not configured')
        try:creds=self._loader(str(self._path),scopes=[CALENDAR_READONLY_SCOPE])
        except Exception as exc:raise CalendarConnectorError('AUTH_REQUIRED','Calendar OAuth credential could not be loaded') from exc
        if not getattr(creds,'has_scopes',lambda _s:False)([CALENDAR_READONLY_SCOPE]):raise CalendarConnectorError('AUTH_REQUIRED','Calendar OAuth credential lacks readonly scope')
        if getattr(creds,'expired',False):
            if not getattr(creds,'refresh_token',None):raise CalendarConnectorError('AUTH_EXPIRED','Calendar OAuth authorization is expired')
            try:creds.refresh(self._request_factory())
            except RefreshError as exc:
                text=str(exc).lower();category='AUTH_REVOKED' if 'invalid_grant' in text or 'revoked' in text else 'AUTH_EXPIRED';raise CalendarConnectorError(category,'Calendar OAuth refresh failed') from exc
            except Exception as exc:raise CalendarConnectorError('AUTH_EXPIRED','Calendar OAuth refresh failed') from exc
        if not getattr(creds,'valid',False):raise CalendarConnectorError('AUTH_REQUIRED','Calendar OAuth authorization is not valid')
        return creds

class CalendarReadAdapter:
    provider='Google Calendar API'
    def __init__(self,credential_source:CalendarCredentialSource|None=None,*,service_factory:Callable[[Any],Any]|None=None,clock:Callable[[],datetime]|None=None):
        self.credentials=credential_source or CalendarCredentialSource();self._service_factory=service_factory or (lambda creds:build('calendar','v3',credentials=creds,cache_discovery=False));self._clock=clock or (lambda:datetime.now(UTC));self._service=None;self._authorized_account_ref=None
    def configured(self):return self.credentials.configured()
    @staticmethod
    def _validate_id(value,label='id'):
        if not isinstance(value,str) or len(value)>MAX_ID_CHARS or not ID_RE.fullmatch(value):raise ValueError(f'invalid Calendar {label}')
        return value
    @staticmethod
    def _account_reference(primary_id):return 'calendar-account:'+hashlib.sha256(CalendarReadAdapter._validate_id(primary_id,'primary calendar id').encode()).hexdigest()[:32]
    def _execute(self,request):
        try:return request.execute()
        except (socket.timeout,TimeoutError) as exc:raise CalendarConnectorError('TIMEOUT','Calendar API request timed out') from exc
        except HttpError as exc:
            status=int(getattr(getattr(exc,'resp',None),'status',0) or 0);category='AUTH_EXPIRED' if status==401 else ('CALENDAR_RATE_LIMIT' if status in {403,429} else 'CALENDAR_API_ERROR');raise CalendarConnectorError(category,'Calendar API request failed') from exc
        except CalendarConnectorError:raise
        except Exception as exc:raise CalendarConnectorError('CALENDAR_API_ERROR','Calendar API request failed') from exc
    @staticmethod
    def _calendar(item):
        if not isinstance(item,dict):raise CalendarConnectorError('MALFORMED_RESPONSE','Calendar summary is malformed')
        cid=CalendarReadAdapter._validate_id(item.get('id'),'calendar_id');summary=item.get('summary','')
        if not isinstance(summary,str) or len(summary)>MAX_SUMMARY_CHARS:raise CalendarConnectorError('MALFORMED_RESPONSE','Calendar summary text is malformed')
        role=item.get('accessRole')
        if role is not None and (not isinstance(role,str) or role not in ACCESS_ROLES):raise CalendarConnectorError('MALFORMED_RESPONSE','Calendar access role is malformed')
        return CalendarSummary(cid,summary,role,bool(item.get('primary',False)))
    def _primary(self,service):
        raw=self._execute(service.calendarList().list(maxResults=MAX_RESULTS,fields='items(id,summary,accessRole,primary),nextPageToken'))
        if not isinstance(raw,dict) or not isinstance(raw.get('items',[]),list):raise CalendarConnectorError('MALFORMED_RESPONSE','Calendar list is malformed')
        items=[self._calendar(x) for x in raw.get('items',[])]
        primary=[x for x in items if x.primary]
        if len(primary)!=1:raise CalendarConnectorError('MALFORMED_RESPONSE','Primary Calendar identity is unavailable or ambiguous')
        return primary[0]
    def _connect(self):
        previous=self._service
        if previous is not None:
            closer=getattr(previous,'close',None)
            if callable(closer):
                try:closer()
                except Exception:pass
            self._service=None
            self._authorized_account_ref=None
        creds=self.credentials.load();service=self._service_factory(creds);primary=self._primary(service);account=self._account_reference(primary.calendar_id);self._service=service;self._authorized_account_ref=account;return service,account
    def authorize(self):
        _service,account=self._connect();return {'authorization_reference':account,'account_ref':account,'granted_scopes':['calendar.read'],'provider_scope':CALENDAR_READONLY_SCOPE,'secret_ref':self.credentials.secret_ref}
    def health(self):
        if not self.configured():return {'ok':False,'status':'AUTH_REQUIRED','authorization_state':'NOT_CONFIGURED','provider':self.provider,'secret_ref':self.credentials.secret_ref}
        try:
            service,account=self._connect();confirmed=self._account_reference(self._primary(service).calendar_id);ok=confirmed==account;return {'ok':ok,'status':'HEALTHY' if ok else 'FAILED','authorization_state':'AUTHORIZED' if ok else 'FAILED','provider':self.provider,'account_ref':account,'scope':CALENDAR_READONLY_SCOPE}
        except CalendarConnectorError as exc:
            auth={'AUTH_EXPIRED':'EXPIRED','AUTH_REVOKED':'REVOKED','AUTH_REQUIRED':'REQUIRED'}.get(exc.category,'FAILED');return {'ok':False,'status':exc.category,'authorization_state':auth,'provider':self.provider,'secret_ref':self.credentials.secret_ref,'error_category':exc.category}
    def _ensure_connected(self):
        if self._service is None or self._authorized_account_ref is None:self._connect()
        return self._service,self._authorized_account_ref
    @staticmethod
    def _max(value,default):
        if value is None:return default
        if isinstance(value,bool) or not isinstance(value,int) or not 1<=value<=MAX_RESULTS:raise ValueError(f'max_results must be 1..{MAX_RESULTS}')
        return value
    @staticmethod
    def _moment(value,label):
        if not isinstance(value,str) or len(value)>64:raise ValueError(f'invalid {label}')
        try:d=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError as exc:raise ValueError(f'invalid {label}') from exc
        if d.tzinfo is None:raise ValueError(f'{label} must include timezone')
        return d.astimezone(UTC)
    def _window(self,p):
        lo=p.get('time_min');hi=p.get('time_max')
        if lo is None and hi is None:
            start=self._clock().astimezone(UTC);end=start+timedelta(days=DEFAULT_WINDOW_DAYS)
        elif lo is None or hi is None:raise ValueError('time_min and time_max must be provided together')
        else:start=self._moment(lo,'time_min');end=self._moment(hi,'time_max')
        if end<=start or end-start>timedelta(days=MAX_WINDOW_DAYS):raise ValueError('Calendar time window is invalid or too broad')
        return start.isoformat().replace('+00:00','Z'),end.isoformat().replace('+00:00','Z')
    @staticmethod
    def _endpoint(value,label):
        if not isinstance(value,dict):raise CalendarConnectorError('MALFORMED_RESPONSE',f'Calendar event {label} is malformed')
        has_date=isinstance(value.get('date'),str);has_dt=isinstance(value.get('dateTime'),str)
        if has_date==has_dt:raise CalendarConnectorError('MALFORMED_RESPONSE',f'Calendar event {label} must contain exactly one temporal value')
        key='date' if has_date else 'dateTime';raw=value[key]
        if len(raw)>64:raise CalendarConnectorError('MALFORMED_RESPONSE',f'Calendar event {label} exceeds bound')
        if has_date:
            try:datetime.strptime(raw,'%Y-%m-%d')
            except ValueError as exc:raise CalendarConnectorError('MALFORMED_RESPONSE',f'Calendar event {label} date is invalid') from exc
            return {'date':raw}
        try:d=datetime.fromisoformat(raw.replace('Z','+00:00'))
        except ValueError as exc:raise CalendarConnectorError('MALFORMED_RESPONSE',f'Calendar event {label} dateTime is invalid') from exc
        if d.tzinfo is None:raise CalendarConnectorError('MALFORMED_RESPONSE',f'Calendar event {label} dateTime lacks timezone')
        return {'dateTime':raw}
    @classmethod
    def _event(cls,item,calendar_id,*,details=False):
        if not isinstance(item,dict):raise CalendarConnectorError('MALFORMED_RESPONSE','Calendar event is malformed')
        eid=cls._validate_id(item.get('id'),'event_id');status=item.get('status')
        if not isinstance(status,str) or status not in STATUS_VALUES:raise CalendarConnectorError('MALFORMED_RESPONSE','Calendar event status is malformed')
        summary=item.get('summary','')
        if not isinstance(summary,str) or len(summary)>MAX_SUMMARY_CHARS:raise CalendarConnectorError('MALFORMED_RESPONSE','Calendar event summary is malformed')
        start=cls._endpoint(item.get('start'),'start');end=cls._endpoint(item.get('end'),'end');all_day='date' in start
        if all_day!=('date' in end):raise CalendarConnectorError('MALFORMED_RESPONSE','Calendar event start/end type mismatch')
        if all_day:
            if end['date']<=start['date']:raise CalendarConnectorError('MALFORMED_RESPONSE','Calendar all-day event has invalid range')
        else:
            sd=datetime.fromisoformat(start['dateTime'].replace('Z','+00:00'));ed=datetime.fromisoformat(end['dateTime'].replace('Z','+00:00'))
            if ed<=sd:raise CalendarConnectorError('MALFORMED_RESPONSE','Calendar timed event has invalid range')
        if details:
            updated=item.get('updated')
            if updated is not None and (not isinstance(updated,str) or len(updated)>64):raise CalendarConnectorError('MALFORMED_RESPONSE','Calendar event updated field is malformed')
            return CalendarEventDetails(eid,calendar_id,status,summary,start,end,all_day,updated)
        return CalendarEventSummary(eid,calendar_id,status,summary,start,end,all_day)
    def invoke(self,operation,payload):
        service,account=self._ensure_connected();p=dict(payload or {})
        if operation=='list_calendars':
            if set(p)-{'max_results'}:raise ValueError('unsupported Calendar list argument')
            maximum=self._max(p.get('max_results'),DEFAULT_CALENDAR_RESULTS);raw=self._execute(service.calendarList().list(maxResults=maximum,fields='items(id,summary,accessRole,primary),nextPageToken'))
            if not isinstance(raw,dict) or not isinstance(raw.get('items',[]),list):raise CalendarConnectorError('MALFORMED_RESPONSE','Calendar list is malformed')
            calendars=tuple(self._calendar(x) for x in raw.get('items',[]))
            if len(calendars)>maximum:raise CalendarConnectorError('MALFORMED_RESPONSE','Calendar returned more calendars than requested')
            return {'kind':'calendar_list','account_ref':account,'provider':self.provider,'operation':operation,'result':CalendarList(calendars,len(calendars),bool(raw.get('nextPageToken'))).to_dict(),'provider_reference':'calendar:calendarList.list'}
        if operation=='list_events':
            if set(p)-{'calendar_id','max_results','time_min','time_max'}:raise ValueError('unsupported Calendar events argument')
            cid=self._validate_id(p.get('calendar_id','primary'),'calendar_id');maximum=self._max(p.get('max_results'),DEFAULT_EVENT_RESULTS);lo,hi=self._window(p);raw=self._execute(service.events().list(calendarId=cid,timeMin=lo,timeMax=hi,maxResults=maximum,singleEvents=True,orderBy='startTime',fields='items(id,status,summary,start,end),nextPageToken'))
            if not isinstance(raw,dict) or not isinstance(raw.get('items',[]),list):raise CalendarConnectorError('MALFORMED_RESPONSE','Calendar event list is malformed')
            events=tuple(self._event(x,cid) for x in raw.get('items',[]))
            if len(events)>maximum:raise CalendarConnectorError('MALFORMED_RESPONSE','Calendar returned more events than requested')
            return {'kind':'event_list','account_ref':account,'provider':self.provider,'operation':operation,'result':CalendarEventList(events,len(events),bool(raw.get('nextPageToken')),lo,hi).to_dict(),'provider_reference':'calendar:events.list'}
        if operation=='get_event':
            if set(p)-{'calendar_id','event_id'}:raise ValueError('unsupported Calendar event argument')
            cid=self._validate_id(p.get('calendar_id','primary'),'calendar_id');eid=self._validate_id(p.get('event_id'),'event_id');raw=self._execute(service.events().get(calendarId=cid,eventId=eid,fields='id,status,summary,start,end,updated'));event=self._event(raw,cid,details=True).to_dict();return {'kind':'event_details','account_ref':account,'provider':self.provider,'operation':operation,'result':event,'provider_reference':'calendar:events.get'}
        raise KeyError(operation)
    @staticmethod
    def _digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    def verify(self,operation,result):
        if not isinstance(result,dict) or result.get('operation')!=operation or result.get('provider')!=self.provider:return {'verified':False,'reason':'provider_or_operation_mismatch','method':'Calendar provider reread'}
        service,account=self._ensure_connected();confirmed=self._account_reference(self._primary(service).calendar_id)
        if confirmed!=account or result.get('account_ref')!=account:return {'verified':False,'reason':'authorized_account_identity_mismatch','method':'Calendar primary identity reread'}
        value=result.get('result')
        if operation=='list_calendars':
            if not isinstance(value,dict) or not isinstance(value.get('calendars'),list) or value.get('result_count')!=len(value['calendars']):return {'verified':False,'reason':'calendar_list_schema_invalid','method':'Calendar primary + calendar reread'}
            hashes=[]
            for item in value['calendars']:
                cal=self._calendar({'id':item.get('calendar_id'),'summary':item.get('summary',''),'accessRole':item.get('access_role'),'primary':item.get('primary',False)});hashes.append(hashlib.sha256(cal.calendar_id.encode()).hexdigest()[:20])
            if value['calendars']:
                first=value['calendars'][0];raw=self._execute(service.calendarList().get(calendarId=first['calendar_id']));
                if raw.get('id')!=first['calendar_id']:return {'verified':False,'reason':'calendar_identity_reread_mismatch','method':'Calendar calendarList.get reread'}
            return {'verified':True,'method':'Calendar primary identity + selected calendar reread','provider':self.provider,'account_ref':account,'calendar_count':len(value['calendars']),'calendar_id_hashes':hashes[:MAX_RESULTS]}
        if operation=='list_events':
            if not isinstance(value,dict) or not isinstance(value.get('events'),list) or value.get('result_count')!=len(value['events']):return {'verified':False,'reason':'event_list_schema_invalid','method':'Calendar event reread'}
            hashes=[]
            for item in value['events']:
                ev=self._event({'id':item.get('event_id'),'status':item.get('status'),'summary':item.get('summary',''),'start':item.get('start'),'end':item.get('end')},item.get('calendar_id'));hashes.append(hashlib.sha256(ev.event_id.encode()).hexdigest()[:20])
            if value['events']:
                first=value['events'][0];raw=self._execute(service.events().get(calendarId=first['calendar_id'],eventId=first['event_id'],fields='id,status,summary,start,end,updated'));again=self._event(raw,first['calendar_id'])
                if again.event_id!=first['event_id'] or again.start!=first['start'] or again.end!=first['end'] or again.status!=first['status']:return {'verified':False,'reason':'event_identity_reread_mismatch','method':'Calendar event reread'}
            return {'verified':True,'method':'Calendar primary identity + selected event reread','provider':self.provider,'account_ref':account,'event_count':len(value['events']),'event_id_hashes':hashes[:MAX_RESULTS]}
        if operation=='get_event':
            if not isinstance(value,dict):return {'verified':False,'reason':'event_schema_invalid','method':'Calendar exact event reread'}
            cid=self._validate_id(value.get('calendar_id'),'calendar_id');eid=self._validate_id(value.get('event_id'),'event_id');raw=self._execute(service.events().get(calendarId=cid,eventId=eid,fields='id,status,summary,start,end,updated'));again=self._event(raw,cid,details=True).to_dict()
            if self._digest(again)!=self._digest(value):return {'verified':False,'reason':'event_reread_mismatch','method':'Calendar exact event reread'}
            return {'verified':True,'method':'Calendar primary identity + exact event reread','provider':self.provider,'account_ref':account,'event_id_hash':hashlib.sha256(eid.encode()).hexdigest()[:20],'event_sha256':self._digest(value),'all_day':bool(value.get('all_day'))}
        return {'verified':False,'reason':'unsupported_operation','method':'Calendar provider reread'}
    def close(self):
        service=self._service
        self._service=None
        self._authorized_account_ref=None
        if hasattr(self,'_creds'):self._creds=None
        closer=getattr(service,'close',None)
        if callable(closer):
            try:closer()
            except Exception:pass
        return {'closed':True}
