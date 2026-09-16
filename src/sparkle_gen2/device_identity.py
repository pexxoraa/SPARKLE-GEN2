from __future__ import annotations
import hashlib,secrets,uuid
from dataclasses import asdict,dataclass
from datetime import UTC,datetime,timedelta
from .core_time import now

@dataclass(slots=True)
class DeviceIdentity:
    device_id:str;name:str;kind:str;os_name:str;capabilities:list[str];status:str;created_at:str;last_seen:str;revoked_at:str|None=None
    def to_dict(self):return asdict(self)

class DeviceIdentityService:
    TOKEN_BYTES=32
    def __init__(self,store):self.store=store
    @staticmethod
    def _hash(value):return hashlib.sha256(value.encode('utf-8')).hexdigest()
    @staticmethod
    def _time(value):return datetime.fromisoformat(value.replace('Z','+00:00'))
    def create_enrollment_code(self,*,ttl_minutes=10):
        if not 1<=int(ttl_minutes)<=60:raise ValueError('enrollment_ttl_out_of_range')
        code='-'.join([secrets.token_hex(2).upper(),secrets.token_hex(2).upper(),secrets.token_hex(2).upper()])
        expires=(datetime.now(UTC)+timedelta(minutes=int(ttl_minutes))).isoformat()
        self.store.save_enrollment_code(self._hash(code),{'expires_at':expires,'created_at':now()})
        return {'code':code,'expires_at':expires}
    def enroll(self,code,*,name,kind,os_name,capabilities):
        if not all(isinstance(x,str) and x.strip() for x in (code,name,kind,os_name)):raise ValueError('invalid_device_enrollment')
        if not isinstance(capabilities,list) or len(capabilities)>64 or any(not isinstance(x,str) or len(x)>80 for x in capabilities):raise ValueError('invalid_device_capabilities')
        key=self._hash(code.strip().upper())
        try:record=self.store.load_enrollment_code(key)
        except KeyError as exc:raise PermissionError('invalid_enrollment_code') from exc
        if self._time(record['expires_at'])<=datetime.now(UTC):self.store.delete_enrollment_code(key);raise PermissionError('expired_enrollment_code')
        self.store.delete_enrollment_code(key);stamp=now();device=DeviceIdentity(uuid.uuid4().hex,name.strip()[:80],kind.strip()[:40],os_name.strip()[:80],sorted(set(capabilities)),'ONLINE',stamp,stamp)
        self.store.save_device_identity(device.device_id,device.to_dict());token=secrets.token_urlsafe(self.TOKEN_BYTES);self.store.save_device_token(self._hash(token),device.device_id,{'created_at':stamp,'last_used':stamp,'status':'ACTIVE'})
        return device,token
    def authenticate(self,token):
        if not isinstance(token,str) or len(token)<32:raise PermissionError('invalid_device_token')
        try:device_id,t=self.store.load_device_token(self._hash(token))
        except KeyError as exc:raise PermissionError('invalid_device_token') from exc
        if t.get('status')!='ACTIVE':raise PermissionError('revoked_device_token')
        devices={d['device_id']:d for d in self.store.device_identities()};d=devices.get(device_id)
        if not d or d.get('revoked_at'):raise PermissionError('revoked_device')
        d['status']='ONLINE';d['last_seen']=now();self.store.save_device_identity(device_id,d);t['last_used']=now();self.store.save_device_token(self._hash(token),device_id,t);return d
    def list(self):return self.store.device_identities()
    def revoke(self,device_id):
        devices={d['device_id']:d for d in self.store.device_identities()}
        if device_id not in devices:raise KeyError(device_id)
        d=devices[device_id];d['status']='REVOKED';d['revoked_at']=now();self.store.save_device_identity(device_id,d);self.store.delete_device_tokens(device_id);return d
    def rename(self,device_id,name):
        if not isinstance(name,str) or not name.strip():raise ValueError('device_name_required')
        devices={d['device_id']:d for d in self.store.device_identities()};d=devices[device_id];d['name']=name.strip()[:80];self.store.save_device_identity(device_id,d);return d
