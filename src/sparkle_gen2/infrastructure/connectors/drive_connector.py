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

DRIVE_READONLY_SCOPE='https://www.googleapis.com/auth/drive.readonly'
DRIVE_SECRET_REF='SPARKLE_DRIVE_TOKEN_FILE'
DEFAULT_RESULTS=10
MAX_RESULTS=25
MAX_QUERY_CHARS=512
MAX_NAME_CHARS=512
MAX_MIME_CHARS=255
MAX_ID_CHARS=1024
ID_RE=re.compile(r'^[A-Za-z0-9_-]{1,1024}$')

class DriveConnectorError(RuntimeError):
    def __init__(self,category:str,message:str):super().__init__(message);self.category=category

@dataclass(frozen=True,slots=True)
class DriveFileSummary:
    file_id:str
    name:str
    mime_type:str
    modified_time:str|None
    size_bytes:int|None
    def to_dict(self):return asdict(self)

@dataclass(frozen=True,slots=True)
class DriveFileList:
    files:tuple[DriveFileSummary,...]
    result_count:int
    has_more:bool
    def to_dict(self):return {'files':[x.to_dict() for x in self.files],'result_count':self.result_count,'has_more':self.has_more}

@dataclass(frozen=True,slots=True)
class DriveFileMetadata:
    file_id:str
    name:str
    mime_type:str
    modified_time:str|None
    size_bytes:int|None
    trashed:bool
    def to_dict(self):return asdict(self)

class DriveCredentialSource:
    """Resolve Drive OAuth credentials from an explicit external configuration reference."""
    def __init__(self,*,secret_ref=DRIVE_SECRET_REF,path:Path|str|None=None,loader:Callable[...,Any]|None=None,request_factory:Callable[[],Any]|None=None):
        self.secret_ref=secret_ref;configured=os.environ.get(secret_ref);self._path=Path(path).expanduser() if path is not None else (Path(configured).expanduser() if configured else None);self._loader=loader or Credentials.from_authorized_user_file;self._request_factory=request_factory or Request
    def configured(self)->bool:
        if self._path is None:return False
        try:return self._path.is_file() and not self._path.is_symlink()
        except OSError:return False
    def load(self):
        if not self.configured():raise DriveConnectorError('AUTH_REQUIRED','Drive OAuth credential reference is not configured')
        try:creds=self._loader(str(self._path),scopes=[DRIVE_READONLY_SCOPE])
        except Exception as exc:raise DriveConnectorError('AUTH_REQUIRED','Drive OAuth credential could not be loaded') from exc
        if not getattr(creds,'has_scopes',lambda _s:False)([DRIVE_READONLY_SCOPE]):raise DriveConnectorError('AUTH_REQUIRED','Drive OAuth credential lacks readonly scope')
        if getattr(creds,'expired',False):
            if not getattr(creds,'refresh_token',None):raise DriveConnectorError('AUTH_EXPIRED','Drive OAuth authorization is expired')
            try:creds.refresh(self._request_factory())
            except RefreshError as exc:
                text=str(exc).lower();category='AUTH_REVOKED' if 'invalid_grant' in text or 'revoked' in text else 'AUTH_EXPIRED';raise DriveConnectorError(category,'Drive OAuth refresh failed') from exc
            except Exception as exc:raise DriveConnectorError('AUTH_EXPIRED','Drive OAuth refresh failed') from exc
        if not getattr(creds,'valid',False):raise DriveConnectorError('AUTH_REQUIRED','Drive OAuth authorization is not valid')
        return creds

class DriveReadAdapter:
    provider='Google Drive API'
    def __init__(self,credential_source:DriveCredentialSource|None=None,*,service_factory:Callable[[Any],Any]|None=None):
        self.credentials=credential_source or DriveCredentialSource();self._service_factory=service_factory or (lambda creds:build('drive','v3',credentials=creds,cache_discovery=False));self._service=None;self._authorized_account_ref=None
    def configured(self):return self.credentials.configured()
    @staticmethod
    def _validate_id(value,label='file_id'):
        if not isinstance(value,str) or len(value)>MAX_ID_CHARS or not ID_RE.fullmatch(value):raise ValueError(f'invalid Drive {label}')
        return value
    @staticmethod
    def _account_ref(permission_id):
        if not isinstance(permission_id,str) or not permission_id or len(permission_id)>1024:raise DriveConnectorError('MALFORMED_RESPONSE','Drive authorized account identity is malformed')
        return 'drive-account:'+hashlib.sha256(permission_id.encode()).hexdigest()[:32]
    def _execute(self,request):
        try:return request.execute()
        except (socket.timeout,TimeoutError) as exc:raise DriveConnectorError('TIMEOUT','Drive API request timed out') from exc
        except HttpError as exc:
            status=int(getattr(getattr(exc,'resp',None),'status',0) or 0);category='AUTH_EXPIRED' if status==401 else ('DRIVE_RATE_LIMIT' if status in {403,429} else 'DRIVE_API_ERROR');raise DriveConnectorError(category,'Drive API request failed') from exc
        except DriveConnectorError:raise
        except Exception as exc:raise DriveConnectorError('DRIVE_API_ERROR','Drive API request failed') from exc
    def _identity(self,service):
        raw=self._execute(service.about().get(fields='user(permissionId)'))
        if not isinstance(raw,dict) or not isinstance(raw.get('user'),dict):raise DriveConnectorError('MALFORMED_RESPONSE','Drive account identity response is malformed')
        return self._account_ref(raw['user'].get('permissionId'))
    def _connect(self):
        previous=self._service
        if previous is not None:
            closer=getattr(previous,'close',None)
            if callable(closer):
                try:closer()
                except Exception:pass
            self._service=None
            self._authorized_account_ref=None
        creds=self.credentials.load();service=self._service_factory(creds);account=self._identity(service);self._service=service;self._authorized_account_ref=account;return service,account
    def authorize(self):
        _service,account=self._connect();return {'authorization_reference':account,'account_ref':account,'granted_scopes':['drive.read'],'provider_scope':DRIVE_READONLY_SCOPE,'secret_ref':self.credentials.secret_ref}
    def health(self):
        if not self.configured():return {'ok':False,'status':'AUTH_REQUIRED','authorization_state':'NOT_CONFIGURED','provider':self.provider,'secret_ref':self.credentials.secret_ref}
        try:
            service,account=self._connect();confirmed=self._identity(service);ok=confirmed==account;return {'ok':ok,'status':'HEALTHY' if ok else 'FAILED','authorization_state':'AUTHORIZED' if ok else 'FAILED','provider':self.provider,'account_ref':account,'scope':DRIVE_READONLY_SCOPE}
        except DriveConnectorError as exc:
            auth={'AUTH_EXPIRED':'EXPIRED','AUTH_REVOKED':'REVOKED','AUTH_REQUIRED':'REQUIRED'}.get(exc.category,'FAILED');return {'ok':False,'status':exc.category,'authorization_state':auth,'provider':self.provider,'secret_ref':self.credentials.secret_ref,'error_category':exc.category}
    def _ensure_connected(self):
        if self._service is None or self._authorized_account_ref is None:self._connect()
        return self._service,self._authorized_account_ref
    @staticmethod
    def _max(value):
        if value is None:return DEFAULT_RESULTS
        if isinstance(value,bool) or not isinstance(value,int) or not 1<=value<=MAX_RESULTS:raise ValueError(f'max_results must be 1..{MAX_RESULTS}')
        return value
    @staticmethod
    def _query(value):
        if value is None:return None
        if not isinstance(value,str) or len(value)>MAX_QUERY_CHARS or any(ord(ch)<32 and ch not in '\t' for ch in value):raise ValueError('Drive query is invalid or too long')
        value=value.strip()
        if not value:raise ValueError('Drive query cannot be blank')
        return value
    @staticmethod
    def _file(item,*,metadata=False):
        if not isinstance(item,dict):raise DriveConnectorError('MALFORMED_RESPONSE','Drive file resource is malformed')
        fid=DriveReadAdapter._validate_id(item.get('id'));name=item.get('name');mime=item.get('mimeType')
        if not isinstance(name,str) or len(name)>MAX_NAME_CHARS:raise DriveConnectorError('MALFORMED_RESPONSE','Drive file name is malformed')
        if not isinstance(mime,str) or not mime or len(mime)>MAX_MIME_CHARS:raise DriveConnectorError('MALFORMED_RESPONSE','Drive MIME type is malformed')
        modified=item.get('modifiedTime')
        if modified is not None and (not isinstance(modified,str) or len(modified)>64):raise DriveConnectorError('MALFORMED_RESPONSE','Drive modifiedTime is malformed')
        size=item.get('size');size_bytes=None
        if size is not None:
            if isinstance(size,bool) or not isinstance(size,(str,int)):
                raise DriveConnectorError('MALFORMED_RESPONSE','Drive size is malformed')
            try:size_bytes=int(size)
            except (ValueError,TypeError) as exc:raise DriveConnectorError('MALFORMED_RESPONSE','Drive size is malformed') from exc
            if size_bytes<0:raise DriveConnectorError('MALFORMED_RESPONSE','Drive size is malformed')
        if metadata:
            trashed=item.get('trashed',False)
            if not isinstance(trashed,bool):raise DriveConnectorError('MALFORMED_RESPONSE','Drive trashed state is malformed')
            return DriveFileMetadata(fid,name,mime,modified,size_bytes,trashed)
        return DriveFileSummary(fid,name,mime,modified,size_bytes)
    def invoke(self,operation,payload):
        service,account=self._ensure_connected();p=dict(payload or {})
        if operation=='list_files':
            if set(p)-{'max_results','query'}:raise ValueError('unsupported Drive list argument')
            maximum=self._max(p.get('max_results'));query=self._query(p.get('query'));kwargs={'pageSize':maximum,'fields':'nextPageToken,files(id,name,mimeType,modifiedTime,size)','orderBy':'modifiedTime desc'}
            if query is not None:kwargs['q']=query
            raw=self._execute(service.files().list(**kwargs))
            if not isinstance(raw,dict) or not isinstance(raw.get('files',[]),list):raise DriveConnectorError('MALFORMED_RESPONSE','Drive file list is malformed')
            files=tuple(self._file(x) for x in raw.get('files',[]))
            if len(files)>maximum:raise DriveConnectorError('MALFORMED_RESPONSE','Drive returned more files than requested')
            return {'kind':'drive_file_list','account_ref':account,'provider':self.provider,'operation':operation,'result':DriveFileList(files,len(files),bool(raw.get('nextPageToken'))).to_dict(),'provider_reference':'drive:files.list'}
        if operation=='get_file_metadata':
            if set(p)-{'file_id'}:raise ValueError('unsupported Drive metadata argument')
            fid=self._validate_id(p.get('file_id'));raw=self._execute(service.files().get(fileId=fid,fields='id,name,mimeType,modifiedTime,size,trashed'));meta=self._file(raw,metadata=True).to_dict();return {'kind':'drive_file_metadata','account_ref':account,'provider':self.provider,'operation':operation,'result':meta,'provider_reference':'drive:files.get'}
        raise KeyError(operation)
    @staticmethod
    def _digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    def verify(self,operation,result):
        if not isinstance(result,dict) or result.get('operation')!=operation or result.get('provider')!=self.provider:return {'verified':False,'reason':'provider_or_operation_mismatch','method':'Drive provider reread'}
        service,account=self._ensure_connected();confirmed=self._identity(service)
        if confirmed!=account or result.get('account_ref')!=account:return {'verified':False,'reason':'authorized_account_identity_mismatch','method':'Drive account identity reread'}
        value=result.get('result')
        if operation=='list_files':
            if not isinstance(value,dict) or not isinstance(value.get('files'),list) or value.get('result_count')!=len(value['files']):return {'verified':False,'reason':'file_list_schema_invalid','method':'Drive selected-file reread'}
            hashes=[];mime_counts={}
            for item in value['files']:
                f=self._file({'id':item.get('file_id'),'name':item.get('name'),'mimeType':item.get('mime_type'),'modifiedTime':item.get('modified_time'),'size':item.get('size_bytes')});hashes.append(hashlib.sha256(f.file_id.encode()).hexdigest()[:20]);mime_counts[f.mime_type]=mime_counts.get(f.mime_type,0)+1
            if value['files']:
                first=value['files'][0];raw=self._execute(service.files().get(fileId=first['file_id'],fields='id,name,mimeType,modifiedTime,size,trashed'));again=self._file(raw,metadata=True)
                if again.file_id!=first['file_id'] or again.name!=first['name'] or again.mime_type!=first['mime_type'] or again.modified_time!=first.get('modified_time') or again.size_bytes!=first.get('size_bytes'):return {'verified':False,'reason':'file_identity_reread_mismatch','method':'Drive files.get reread'}
            return {'verified':True,'method':'Drive account identity + selected file reread','provider':self.provider,'account_ref':account,'file_count':len(value['files']),'file_id_hashes':hashes[:MAX_RESULTS],'mime_type_counts':mime_counts}
        if operation=='get_file_metadata':
            if not isinstance(value,dict):return {'verified':False,'reason':'file_metadata_schema_invalid','method':'Drive exact file reread'}
            fid=self._validate_id(value.get('file_id'));raw=self._execute(service.files().get(fileId=fid,fields='id,name,mimeType,modifiedTime,size,trashed'));again=self._file(raw,metadata=True).to_dict()
            if self._digest(again)!=self._digest(value):return {'verified':False,'reason':'file_metadata_reread_mismatch','method':'Drive exact file reread'}
            return {'verified':True,'method':'Drive account identity + exact file metadata reread','provider':self.provider,'account_ref':account,'file_id_hash':hashlib.sha256(fid.encode()).hexdigest()[:20],'metadata_sha256':self._digest(value),'mime_type':value.get('mime_type')}
        return {'verified':False,'reason':'unsupported_operation','method':'Drive provider reread'}
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
