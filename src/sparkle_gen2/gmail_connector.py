from __future__ import annotations
import hashlib,json,os,re,socket
from dataclasses import asdict,dataclass
from pathlib import Path
from typing import Any,Callable

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

GMAIL_READONLY_SCOPE='https://www.googleapis.com/auth/gmail.readonly'
GMAIL_SECRET_REF='SPARKLE_GMAIL_TOKEN_FILE'
MAX_RESULTS=25
DEFAULT_RESULTS=5
MAX_QUERY_CHARS=512
MAX_HEADERS=10
MAX_HEADER_VALUE_CHARS=2048
MAX_LABELS=100
MAX_SNIPPET_CHARS=500
MESSAGE_ID_RE=re.compile(r'^[A-Za-z0-9_-]{1,128}$')
HEADER_NAME_RE=re.compile(r'^[A-Za-z0-9-]{1,64}$')
DEFAULT_HEADERS=('From','To','Subject','Date')

class GmailConnectorError(RuntimeError):
    def __init__(self,category:str,message:str):super().__init__(message);self.category=category

@dataclass(frozen=True,slots=True)
class GmailMessageSummary:
    message_id:str
    thread_id:str
    def to_dict(self):return asdict(self)

@dataclass(frozen=True,slots=True)
class GmailMessageMetadata:
    message_id:str
    thread_id:str
    label_ids:tuple[str,...]
    headers:tuple[tuple[str,str],...]
    internal_date:str|None
    snippet:str|None=None
    def to_dict(self):
        return {'message_id':self.message_id,'thread_id':self.thread_id,'label_ids':list(self.label_ids),'headers':[{'name':n,'value':v} for n,v in self.headers],'internal_date':self.internal_date,'snippet':self.snippet}

@dataclass(frozen=True,slots=True)
class GmailMessageList:
    messages:tuple[GmailMessageSummary,...]
    result_count:int
    has_more:bool
    def to_dict(self):return {'messages':[x.to_dict() for x in self.messages],'result_count':self.result_count,'has_more':self.has_more}

class GmailCredentialSource:
    """Symbolic credential reference resolved only inside the established workstation config boundary."""
    def __init__(self,*,secret_ref=GMAIL_SECRET_REF,path:Path|str|None=None,loader:Callable[...,Any]|None=None,request_factory:Callable[[],Any]|None=None):
        self.secret_ref=secret_ref
        configured=os.environ.get('SPARKLE_GMAIL_TOKEN_FILE')
        self._path=Path(path).expanduser() if path is not None else (Path(configured).expanduser() if configured else None)
        self._loader=loader or Credentials.from_authorized_user_file
        self._request_factory=request_factory or Request
    def configured(self)->bool:
        if self._path is None:return False
        try:return self._path.is_file() and not self._path.is_symlink()
        except OSError:return False
    def load(self):
        if not self.configured():raise GmailConnectorError('AUTH_REQUIRED','Gmail OAuth credential reference is not configured')
        try:creds=self._loader(str(self._path),scopes=[GMAIL_READONLY_SCOPE])
        except Exception as exc:raise GmailConnectorError('AUTH_REQUIRED','Gmail OAuth credential could not be loaded') from exc
        if not getattr(creds,'has_scopes',lambda _s:False)([GMAIL_READONLY_SCOPE]):raise GmailConnectorError('AUTH_REQUIRED','Gmail OAuth credential lacks readonly scope')
        if getattr(creds,'expired',False):
            if not getattr(creds,'refresh_token',None):raise GmailConnectorError('AUTH_EXPIRED','Gmail OAuth authorization is expired')
            try:creds.refresh(self._request_factory())
            except RefreshError as exc:
                text=str(exc).lower();category='AUTH_REVOKED' if 'invalid_grant' in text or 'revoked' in text else 'AUTH_EXPIRED'
                raise GmailConnectorError(category,'Gmail OAuth refresh failed') from exc
            except Exception as exc:raise GmailConnectorError('AUTH_EXPIRED','Gmail OAuth refresh failed') from exc
        if not getattr(creds,'valid',False):raise GmailConnectorError('AUTH_REQUIRED','Gmail OAuth authorization is not valid')
        return creds

class GmailReadAdapter:
    """Read-only Gmail adapter. No message body retrieval or mailbox mutation operations exist here."""
    provider='Google Gmail API'
    def __init__(self,credential_source:GmailCredentialSource|None=None,*,service_factory:Callable[[Any],Any]|None=None):
        self.credentials=credential_source or GmailCredentialSource();self._service_factory=service_factory or (lambda creds:build('gmail','v1',credentials=creds,cache_discovery=False));self._service=None;self._creds=None;self._authorized_account_ref=None
    def configured(self):return self.credentials.configured()
    @staticmethod
    def _account_reference(profile):
        if not isinstance(profile,dict) or not isinstance(profile.get('emailAddress'),str) or not profile['emailAddress'].strip():raise GmailConnectorError('MALFORMED_RESPONSE','Gmail profile identity is malformed')
        return 'gmail-account:'+hashlib.sha256(profile['emailAddress'].strip().lower().encode()).hexdigest()[:32]
    def _execute(self,request):
        try:return request.execute()
        except socket.timeout as exc:raise GmailConnectorError('TIMEOUT','Gmail API request timed out') from exc
        except TimeoutError as exc:raise GmailConnectorError('TIMEOUT','Gmail API request timed out') from exc
        except HttpError as exc:
            status=int(getattr(getattr(exc,'resp',None),'status',0) or 0)
            category='AUTH_EXPIRED' if status==401 else ('GMAIL_RATE_LIMIT' if status==429 else 'GMAIL_API_ERROR')
            raise GmailConnectorError(category,'Gmail API request failed') from exc
        except GmailConnectorError:raise
        except Exception as exc:raise GmailConnectorError('GMAIL_API_ERROR','Gmail API request failed') from exc
    def _connect(self):
        previous=self._service
        if previous is not None:
            closer=getattr(previous,'close',None)
            if callable(closer):
                try:closer()
                except Exception:pass
            self._service=None
            self._authorized_account_ref=None
        creds=self.credentials.load();service=self._service_factory(creds);profile=self._execute(service.users().getProfile(userId='me'));account=self._account_reference(profile);self._creds=creds;self._service=service;self._authorized_account_ref=account;return service,account
    def authorize(self):
        _service,account=self._connect();return {'authorization_reference':account,'account_ref':account,'granted_scopes':['gmail.read'],'provider_scope':GMAIL_READONLY_SCOPE,'secret_ref':self.credentials.secret_ref}
    def health(self):
        if not self.configured():return {'ok':False,'status':'AUTH_REQUIRED','authorization_state':'NOT_CONFIGURED','provider':self.provider,'secret_ref':self.credentials.secret_ref}
        try:
            service,account=self._connect();profile=self._execute(service.users().getProfile(userId='me'));confirmed=self._account_reference(profile)
            return {'ok':confirmed==account,'status':'HEALTHY' if confirmed==account else 'FAILED','authorization_state':'AUTHORIZED' if confirmed==account else 'FAILED','provider':self.provider,'account_ref':account,'scope':GMAIL_READONLY_SCOPE}
        except GmailConnectorError as exc:
            auth={'AUTH_EXPIRED':'EXPIRED','AUTH_REVOKED':'REVOKED','AUTH_REQUIRED':'REQUIRED'}.get(exc.category,'FAILED')
            return {'ok':False,'status':exc.category,'authorization_state':auth,'provider':self.provider,'secret_ref':self.credentials.secret_ref,'error_category':exc.category}
    @staticmethod
    def _validate_message_id(value):
        if not isinstance(value,str) or not MESSAGE_ID_RE.fullmatch(value):raise ValueError('invalid Gmail message_id')
        return value
    @staticmethod
    def _headers(value):
        if value is None:return list(DEFAULT_HEADERS)
        if not isinstance(value,list) or not 1<=len(value)<=MAX_HEADERS:raise ValueError('headers must be a bounded non-empty list')
        out=[]
        for name in value:
            if not isinstance(name,str) or not HEADER_NAME_RE.fullmatch(name):raise ValueError('invalid Gmail metadata header name')
            if name.lower() not in {x.lower() for x in DEFAULT_HEADERS}:raise ValueError('Gmail metadata header not allowed')
            if name.lower() not in {x.lower() for x in out}:out.append(name)
        return out
    @staticmethod
    def _summary(item):
        if not isinstance(item,dict):raise GmailConnectorError('MALFORMED_RESPONSE','Gmail message summary is malformed')
        mid=GmailReadAdapter._validate_message_id(item.get('id'));tid=GmailReadAdapter._validate_message_id(item.get('threadId'));return GmailMessageSummary(mid,tid)
    @staticmethod
    def _metadata(item,requested_headers,include_snippet=False):
        if not isinstance(item,dict):raise GmailConnectorError('MALFORMED_RESPONSE','Gmail message metadata is malformed')
        mid=GmailReadAdapter._validate_message_id(item.get('id'));tid=GmailReadAdapter._validate_message_id(item.get('threadId'))
        labels=item.get('labelIds',[])
        if not isinstance(labels,list) or len(labels)>MAX_LABELS or any(not isinstance(x,str) or len(x)>128 for x in labels):raise GmailConnectorError('MALFORMED_RESPONSE','Gmail labels are malformed')
        headers=((item.get('payload') or {}).get('headers') if isinstance(item.get('payload'),dict) else None)
        if not isinstance(headers,list):raise GmailConnectorError('MALFORMED_RESPONSE','Gmail metadata headers are malformed')
        wanted={x.lower() for x in requested_headers};bounded=[];seen=set()
        for h in headers:
            if not isinstance(h,dict) or not isinstance(h.get('name'),str) or not isinstance(h.get('value'),str):raise GmailConnectorError('MALFORMED_RESPONSE','Gmail metadata header is malformed')
            key=h['name'].lower()
            if key in wanted and key not in seen:
                if len(h['value'])>MAX_HEADER_VALUE_CHARS:raise GmailConnectorError('MALFORMED_RESPONSE','Gmail metadata header exceeds bound')
                bounded.append((h['name'],h['value']));seen.add(key)
        if not wanted.issubset(seen):raise GmailConnectorError('MALFORMED_RESPONSE','Requested Gmail metadata header missing')
        internal=item.get('internalDate')
        if internal is not None and (not isinstance(internal,str) or not internal.isdigit() or len(internal)>32):raise GmailConnectorError('MALFORMED_RESPONSE','Gmail internalDate is malformed')
        snippet=None
        if include_snippet:
            raw=item.get('snippet','')
            if not isinstance(raw,str):raise GmailConnectorError('MALFORMED_RESPONSE','Gmail snippet is malformed')
            snippet=raw[:MAX_SNIPPET_CHARS]
        return GmailMessageMetadata(mid,tid,tuple(labels),tuple(bounded),internal,snippet)
    def _ensure_connected(self):
        if self._service is None or self._authorized_account_ref is None:self._connect()
        return self._service,self._authorized_account_ref
    def invoke(self,operation,payload):
        service,account=self._ensure_connected();p=dict(payload or {})
        if operation=='list_messages':
            allowed={'max_results','query'}
            if set(p)-allowed:raise ValueError('unsupported Gmail list argument')
            max_results=p.get('max_results',DEFAULT_RESULTS)
            if isinstance(max_results,bool) or not isinstance(max_results,int) or not 1<=max_results<=MAX_RESULTS:raise ValueError('max_results must be 1..25')
            query=p.get('query')
            if query is not None and (not isinstance(query,str) or not query.strip() or len(query)>MAX_QUERY_CHARS):raise ValueError('Gmail query is invalid or too long')
            kwargs={'userId':'me','maxResults':max_results}
            if query is not None:kwargs['q']=query.strip()
            raw=self._execute(service.users().messages().list(**kwargs))
            if not isinstance(raw,dict) or not isinstance(raw.get('messages',[]),list):raise GmailConnectorError('MALFORMED_RESPONSE','Gmail message list is malformed')
            messages=tuple(self._summary(x) for x in raw.get('messages',[]))
            if len(messages)>max_results:raise GmailConnectorError('MALFORMED_RESPONSE','Gmail returned more messages than requested')
            result=GmailMessageList(messages,len(messages),bool(raw.get('nextPageToken'))).to_dict();return {'kind':'message_list','account_ref':account,'provider':self.provider,'operation':'list_messages','result':result,'provider_reference':'gmail:users.messages.list'}
        if operation=='get_message_metadata':
            allowed={'message_id','headers','include_snippet'}
            if set(p)-allowed:raise ValueError('unsupported Gmail metadata argument')
            mid=self._validate_message_id(p.get('message_id'));headers=self._headers(p.get('headers'));include=bool(p.get('include_snippet',False))
            raw=self._execute(service.users().messages().get(userId='me',id=mid,format='metadata',metadataHeaders=headers));metadata=self._metadata(raw,headers,include).to_dict();return {'kind':'message_metadata','account_ref':account,'provider':self.provider,'operation':'get_message_metadata','result':metadata,'requested_headers':headers,'provider_reference':'gmail:users.messages.get'}
        raise KeyError(operation)
    @staticmethod
    def _digest_metadata(value):
        safe={'message_id':value['message_id'],'thread_id':value['thread_id'],'label_ids':sorted(value.get('label_ids',[])),'headers':value.get('headers',[]),'internal_date':value.get('internal_date'),'snippet':value.get('snippet')}
        return hashlib.sha256(json.dumps(safe,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    def verify(self,operation,result):
        if not isinstance(result,dict) or result.get('operation')!=operation or result.get('provider')!=self.provider:return {'verified':False,'reason':'provider_or_operation_mismatch','method':'Gmail provider reread'}
        service,account=self._ensure_connected();profile=self._execute(service.users().getProfile(userId='me'))
        if self._account_reference(profile)!=account or result.get('account_ref')!=account:return {'verified':False,'reason':'authorized_account_identity_mismatch','method':'Gmail profile reread'}
        if operation=='list_messages':
            value=result.get('result');
            if not isinstance(value,dict) or not isinstance(value.get('messages'),list) or value.get('result_count')!=len(value['messages']):return {'verified':False,'reason':'message_list_schema_invalid','method':'Gmail profile + message reread'}
            hashes=[]
            for item in value['messages']:
                summary=self._summary({'id':item.get('message_id'),'threadId':item.get('thread_id')});hashes.append(hashlib.sha256(summary.message_id.encode()).hexdigest()[:20])
            if value['messages']:
                first=value['messages'][0];raw=self._execute(service.users().messages().get(userId='me',id=first['message_id'],format='metadata',metadataHeaders=[]))
                if raw.get('id')!=first['message_id'] or raw.get('threadId')!=first['thread_id']:return {'verified':False,'reason':'message_identity_reread_mismatch','method':'Gmail message metadata reread'}
            return {'verified':True,'method':'Gmail profile identity + bounded message metadata reread','provider':self.provider,'account_ref':account,'message_count':len(value['messages']),'message_id_hashes':hashes[:MAX_RESULTS]}
        if operation=='get_message_metadata':
            value=result.get('result');headers=result.get('requested_headers')
            if not isinstance(value,dict) or not isinstance(headers,list):return {'verified':False,'reason':'metadata_schema_invalid','method':'Gmail metadata reread'}
            raw=self._execute(service.users().messages().get(userId='me',id=self._validate_message_id(value.get('message_id')),format='metadata',metadataHeaders=self._headers(headers)));again=self._metadata(raw,self._headers(headers),value.get('snippet') is not None).to_dict()
            if self._digest_metadata(again)!=self._digest_metadata(value):return {'verified':False,'reason':'metadata_reread_mismatch','method':'Gmail metadata reread'}
            return {'verified':True,'method':'Gmail profile identity + exact metadata reread','provider':self.provider,'account_ref':account,'message_id_hash':hashlib.sha256(value['message_id'].encode()).hexdigest()[:20],'metadata_sha256':self._digest_metadata(value),'header_count':len(value.get('headers',[])),'label_count':len(value.get('label_ids',[]))}
        return {'verified':False,'reason':'unsupported_operation','method':'Gmail provider reread'}
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
