from __future__ import annotations
import hashlib,json,math,os,select,subprocess,time,uuid
from dataclasses import asdict,dataclass
from pathlib import Path
from typing import Any

SYSTEM_PYTHON='/usr/bin/python3'
MAX_HELPER_REQUEST=16384;MAX_HELPER_RESPONSE=65536;HELPER_TIMEOUT=25
MAX_GUI_ACTIONS=8;MIN_CLICK_INTERVAL=.20
SAFE_KEYS=frozenset({'Escape','Tab','Left','Up','Right','Down','PageUp','PageDown'})
READ_ACTIONS=frozenset({'inspect','status','screenshot','observe'})
CONTROL_ACTIONS=frozenset({'pointer_move','pointer_click','pointer_scroll','key_press','key_release'})

class ComputerAdapterError(RuntimeError):
    def __init__(self,category:str,message:str):super().__init__(message);self.category=category

@dataclass(frozen=True,slots=True)
class ComputerScreenshotReference:
    reference:str;sha256:str;width:int;height:int;size_bytes:int;source:str
    def to_dict(self):return asdict(self)
@dataclass(frozen=True,slots=True)
class ComputerObservation:
    session_reference:str|None;image:ComputerScreenshotReference;captured_at_ns:int;stream_verified:bool
    def to_dict(self):return {'session_reference':self.session_reference,'image':self.image.to_dict(),'captured_at_ns':self.captured_at_ns,'stream_verified':self.stream_verified}
@dataclass(frozen=True,slots=True)
class ComputerActionResult:
    action:str;session_reference:str;accepted:bool;action_index:int
    def to_dict(self):return asdict(self)

class ComputerAdapter:
    provider='XDG Desktop Portal (GNOME Wayland)'
    def __init__(self,*,owner_user_id='user',device_id=None,helper_path=None,popen_factory=None):
        self.owner_user_id=owner_user_id;self.device_id=device_id or self._device_identity();self.helper_path=Path(helper_path or Path(__file__).with_name('computer_portal_helper.py')).resolve();self._popen=popen_factory or subprocess.Popen;self._proc=None;self._closed=False;self._session_ref=None;self._last_observation=None;self._actions=0;self._last_click=0.0;self._pressed=set();self._portal=None
    @staticmethod
    def _device_identity():
        raw=''
        try:raw=Path('/etc/machine-id').read_text(encoding='ascii').strip()
        except Exception:raw=os.uname().nodename
        return 'computer-device:'+hashlib.sha256(('SPARKLE-COMPUTER/1\0'+raw).encode()).hexdigest()[:32]
    @property
    def bound_device_id(self):return self.device_id
    def _env(self):
        uid=os.getuid();runtime=f'/run/user/{uid}';wayland='wayland-0'
        return {'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','XDG_RUNTIME_DIR':runtime,'DBUS_SESSION_BUS_ADDRESS':f'unix:path={runtime}/bus','WAYLAND_DISPLAY':wayland,'DISPLAY':':0','XDG_SESSION_TYPE':'wayland'}
    def _runtime_available(self):
        env=self._env();return Path(SYSTEM_PYTHON).is_file() and os.access(SYSTEM_PYTHON,os.X_OK) and self.helper_path.is_file() and Path(env['XDG_RUNTIME_DIR'],'bus').exists() and Path(env['XDG_RUNTIME_DIR'],env['WAYLAND_DISPLAY']).exists()
    def _ensure_helper(self):
        if self._closed:raise ComputerAdapterError('REVOKED','computer adapter is closed')
        if self._proc is not None and self._proc.poll() is None:return
        if not self._runtime_available():raise ComputerAdapterError('UNAVAILABLE','GNOME Wayland portal runtime is unavailable')
        try:self._proc=self._popen([SYSTEM_PYTHON,str(self.helper_path),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1,env=self._env(),start_new_session=True)
        except Exception as exc:raise ComputerAdapterError('UNAVAILABLE','portal helper could not start') from exc
    def _call(self,cmd,args=None,timeout=HELPER_TIMEOUT):
        if cmd not in {'discover','status','screenshot','create_session','observe','pointer_move','pointer_click','pointer_scroll','key_press','key_release','close'}:raise PermissionError('computer_helper_command_not_allowlisted')
        self._ensure_helper();payload=json.dumps({'cmd':cmd,'args':dict(args or {})},separators=(',',':'))
        if len(payload.encode())>MAX_HELPER_REQUEST:raise ValueError('computer helper request exceeds bound')
        try:
            self._proc.stdin.write(payload+'\n');self._proc.stdin.flush();ready,_,_=select.select([self._proc.stdout],[],[],timeout)
            if not ready:raise ComputerAdapterError('TIMEOUT','portal helper response timed out')
            line=self._proc.stdout.readline(MAX_HELPER_RESPONSE+1)
        except ComputerAdapterError:raise
        except Exception as exc:raise ComputerAdapterError('HELPER_FAILURE','portal helper communication failed') from exc
        if not line or len(line.encode())>MAX_HELPER_RESPONSE:raise ComputerAdapterError('HELPER_FAILURE','portal helper response invalid')
        try:reply=json.loads(line)
        except Exception as exc:raise ComputerAdapterError('HELPER_FAILURE','portal helper returned malformed JSON') from exc
        if reply.get('ok') is not True:
            err=str(reply.get('error','portal_failure'))
            cat='AUTH_DENIED' if 'denied' in err or 'cancelled' in err else ('AUTH_REQUIRED' if 'authorization_required' in err else ('STALE_SESSION' if 'stale_session' in err else 'PORTAL_FAILURE'))
            raise ComputerAdapterError(cat,err)
        result=reply.get('result')
        if not isinstance(result,dict):raise ComputerAdapterError('HELPER_FAILURE','portal helper result malformed')
        return result
    def _stop_helper(self):
        proc=self._proc
        if proc is None:return
        if proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=3)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=2)
        for stream in (proc.stdin,proc.stdout):
            try:
                if stream is not None:stream.close()
            except Exception:pass
        self._proc=None
    def _one_shot(self,cmd,args=None,timeout=HELPER_TIMEOUT):
        had=self._proc is not None and self._proc.poll() is None
        try:return self._call(cmd,args,timeout)
        finally:
            if not had and self._session_ref is None:self._stop_helper()
    def configured(self):
        if not self._runtime_available() or self._closed:return False
        try:
            d=self._one_shot('discover',timeout=8);self._portal=d;return d.get('remote_desktop_version')==2 and d.get('screencast_version')>=5 and d.get('screenshot_version')==2 and int(d.get('remote_device_types',0))&3==3 and int(d.get('screen_source_types',0))&1==1
        except Exception:return False
    def authorize(self):
        if not self.configured():raise ComputerAdapterError('UNAVAILABLE','required portal capabilities are unavailable')
        return {'authorization_reference':'xdg-portal:'+hashlib.sha256((self.device_id+'\0'+json.dumps(self._portal,sort_keys=True)).encode()).hexdigest()[:24],'granted_scopes':['computer.read','computer.act'],'device_id':self.device_id}
    def health(self):
        try:
            d=self._one_shot('discover',timeout=8);ok=d.get('remote_desktop_version')==2 and d.get('screenshot_version')==2 and int(d.get('remote_device_types',0))&3==3 and int(d.get('screen_source_types',0))&1==1
            return {'ok':ok,'status':'HEALTHY' if ok else 'UNAVAILABLE','authorization_state':'AUTHORIZED' if ok else 'FAILED','provider':self.provider,'device_id':self.device_id,'portal':{k:d.get(k) for k in ('remote_desktop_version','remote_device_types','screencast_version','screen_source_types','screenshot_version')},'session_authorization':'AUTHORIZED' if self._session_ref else 'REQUIRED','active_session':bool(self._session_ref),'action_count':self._actions}
        except Exception:return {'ok':False,'status':'UNAVAILABLE','authorization_state':'FAILED','provider':self.provider,'device_id':self.device_id,'session_authorization':'REQUIRED','active_session':False}
    def _bind(self,owner_user_id,device_id):
        if owner_user_id!=self.owner_user_id:raise PermissionError('computer_owner_mismatch')
        if device_id!=self.device_id:raise PermissionError('computer_device_mismatch')
        if self._closed:raise PermissionError('computer_adapter_revoked')
    def _session(self,provided):
        if not self._session_ref:raise ComputerAdapterError('AUTH_REQUIRED','computer session authorization is required')
        if provided!=self._session_ref:raise ComputerAdapterError('STALE_SESSION','computer session reference is stale')
    @staticmethod
    def _image(result):
        sha=result.get('sha256');w=result.get('width');h=result.get('height');size=result.get('size_bytes');source=result.get('source')
        if not isinstance(sha,str) or len(sha)!=64 or not isinstance(w,int) or not isinstance(h,int) or w<=0 or h<=0 or not isinstance(size,int) or size<=0 or not isinstance(source,str):raise ComputerAdapterError('MALFORMED_OBSERVATION','portal observation is malformed')
        return ComputerScreenshotReference('portal-image:'+sha[:24],sha,w,h,size,source)
    def _observe(self):
        raw=self._call('observe');img=self._image(raw);obs=ComputerObservation(self._session_ref,img,int(raw.get('captured_at_ns',0)),raw.get('source')=='screencast-pipewire');self._last_observation=obs;return obs
    def _read(self,p):
        if set(p)-{'action','authorize_session','session_id'}:raise ValueError('unsupported computer.read argument')
        action=str(p.get('action','status'))
        if action not in READ_ACTIONS:raise PermissionError('computer_read_action_not_allowlisted')
        if action in {'status','inspect'}:
            d=self._call('status') if self._session_ref else self._one_shot('discover');return {'action':action,'portal':{k:d.get(k) for k in ('remote_desktop_version','remote_device_types','screencast_version','screen_source_types','screenshot_version')},'session_authorization':'AUTHORIZED' if self._session_ref else 'REQUIRED','active_session':bool(self._session_ref),'session_reference':self._session_ref,'selected_devices':int(d.get('selected_devices',0) or 0),'stream_count':int(d.get('stream_count',0) or 0)}
        if action=='screenshot':
            raw=self._one_shot('screenshot');img=self._image(raw);return {'action':action,'observation':ComputerObservation(None,img,int(raw.get('captured_at_ns',0)),False).to_dict()}
        if action=='observe':
            if self._session_ref is None:
                if p.get('authorize_session') is not True:raise ComputerAdapterError('AUTH_REQUIRED','explicit portal session authorization is required')
                state=self._call('create_session',timeout=70);self._session_ref='computer-session:'+uuid.uuid4().hex;self._actions=0;self._pressed.clear()
                if int(state.get('selected_devices',0))&3!=3:raise ComputerAdapterError('AUTH_DENIED','required pointer/keyboard devices were not granted')
            elif p.get('session_id') is not None:self._session(p.get('session_id'))
            obs=self._observe();return {'action':action,'observation':obs.to_dict(),'session_reference':self._session_ref}
        raise KeyError(action)
    def _act(self,p):
        allowed={'action','session_id','x','y','dx','dy','key'}
        if set(p)-allowed:raise ValueError('unsupported computer.act argument')
        action=str(p.get('action',''))
        if action not in CONTROL_ACTIONS:raise PermissionError('computer_control_action_not_allowlisted')
        self._session(p.get('session_id'))
        if self._actions>=MAX_GUI_ACTIONS:raise ComputerAdapterError('ACTION_LIMIT','computer session action limit reached')
        if self._last_observation is None or not self._last_observation.stream_verified:raise ComputerAdapterError('OBSERVATION_REQUIRED','fresh verified screen stream observation is required')
        if action=='pointer_move':
            x=p.get('x');y=p.get('y');w=self._last_observation.image.width;h=self._last_observation.image.height
            for v in (x,y):
                if not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(float(v)):raise ValueError('pointer coordinate invalid')
            if x<0 or y<0 or x>=w or y>=h:raise ValueError('pointer coordinate outside verified stream bounds')
            raw=self._call('pointer_move',{'x':float(x),'y':float(y)})
        elif action=='pointer_click':
            now=time.monotonic()
            if now-self._last_click<MIN_CLICK_INTERVAL:raise ComputerAdapterError('CLICK_RATE_LIMIT','click frequency limit reached')
            raw=self._call('pointer_click');self._last_click=now
        elif action=='pointer_scroll':raw=self._call('pointer_scroll',{'dx':p.get('dx',0),'dy':p.get('dy',0)})
        else:
            key=str(p.get('key',''))
            if key not in SAFE_KEYS:raise PermissionError('computer_key_not_allowlisted')
            if action=='key_press':
                if key in self._pressed:raise ComputerAdapterError('KEY_STATE','key already pressed')
                raw=self._call('key_press',{'key':key});self._pressed.add(key)
            else:
                if key not in self._pressed:raise ComputerAdapterError('KEY_STATE','key is not pressed')
                raw=self._call('key_release',{'key':key});self._pressed.remove(key)
        self._actions+=1;return ComputerActionResult(action,self._session_ref,bool(raw.get('accepted')),self._actions).to_dict()|{'key':p.get('key') if action.startswith('key_') else None}
    def invoke_with_context(self,operation,payload,*,owner_user_id=None,device_id=None,**_context):
        self._bind(owner_user_id,device_id);p=dict(payload or {})
        if operation=='read':result=self._read(p)
        elif operation=='act':result=self._act(p)
        else:raise KeyError(operation)
        session_provider_ref=None if self._session_ref is None else 'computer-session-ref:'+hashlib.sha256(self._session_ref.encode()).hexdigest()[:24]
        return {'provider':self.provider,'operation':operation,'device_reference':hashlib.sha256(self.device_id.encode()).hexdigest()[:20],'result':result,'provider_reference':session_provider_ref}
    def invoke(self,operation,payload):return self.invoke_with_context(operation,payload,owner_user_id=self.owner_user_id,device_id=self.device_id)
    @staticmethod
    def _digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    def verify_with_context(self,operation,result,*,owner_user_id=None,**_context):
        if owner_user_id!=self.owner_user_id:return {'verified':False,'reason':'computer_owner_mismatch','method':'portal fresh-observation verification'}
        if not isinstance(result,dict) or result.get('provider')!=self.provider or result.get('operation')!=operation:return {'verified':False,'reason':'provider_or_operation_mismatch','method':'portal fresh-observation verification'}
        value=result.get('result') or {}
        try:
            if operation=='read':
                action=value.get('action')
                if action in {'status','inspect'}:
                    fresh=self._one_shot('discover');ok=int(fresh.get('remote_device_types',0))&3==3 and int(fresh.get('screen_source_types',0))&1==1;return {'verified':bool(ok),'method':'fresh XDG portal capability reread','portal_digest':self._digest({k:fresh.get(k) for k in ('remote_desktop_version','remote_device_types','screencast_version','screen_source_types','screenshot_version')}),'device_reference':result.get('device_reference')}
                if action=='screenshot':
                    fresh=self._one_shot('screenshot');img=self._image(fresh);return {'verified':True,'method':'fresh Screenshot portal reread','fresh_observation_sha256':img.sha256,'fresh_dimensions':[img.width,img.height],'device_reference':result.get('device_reference')}
                if action=='observe':
                    if value.get('session_reference')!=self._session_ref:return {'verified':False,'reason':'session_reference_mismatch','method':'fresh ScreenCast observation'}
                    fresh=self._observe();return {'verified':fresh.stream_verified,'method':'fresh ScreenCast/PipeWire frame observation','fresh_observation_sha256':fresh.image.sha256,'fresh_dimensions':[fresh.image.width,fresh.image.height],'session_reference_hash':hashlib.sha256(self._session_ref.encode()).hexdigest()[:24],'device_reference':result.get('device_reference')}
            if operation=='act':
                if value.get('session_reference')!=self._session_ref or value.get('accepted') is not True:return {'verified':False,'reason':'action_or_session_mismatch','method':'portal action + fresh ScreenCast observation'}
                state=self._call('status');action=value.get('action');key=value.get('key');pressed=set(state.get('pressed_keys') or [])
                if action=='key_press' and key not in pressed:return {'verified':False,'reason':'key_press_state_missing','method':'portal key state reread'}
                if action=='key_release' and key in pressed:return {'verified':False,'reason':'key_release_state_mismatch','method':'portal key state reread'}
                fresh=self._observe();return {'verified':fresh.stream_verified and bool(state.get('session_handle_present')),'method':'portal action accepted + active session reread + fresh ScreenCast frame','action':action,'fresh_observation_sha256':fresh.image.sha256,'fresh_dimensions':[fresh.image.width,fresh.image.height],'session_reference_hash':hashlib.sha256(self._session_ref.encode()).hexdigest()[:24],'device_reference':result.get('device_reference')}
        except Exception:return {'verified':False,'reason':'fresh_portal_verification_failed','method':'portal fresh-observation verification'}
        return {'verified':False,'reason':'unsupported_operation','method':'portal fresh-observation verification'}
    def verify(self,operation,result):return self.verify_with_context(operation,result,owner_user_id=self.owner_user_id)
    def close(self):
        try:
            if self._proc is not None and self._proc.poll() is None:
                try:self._call('close',timeout=8)
                except Exception:pass
        finally:
            self._stop_helper();self._session_ref=None;self._last_observation=None;self._pressed.clear();self._closed=True
        return {'status':'closed','device_reference':hashlib.sha256(self.device_id.encode()).hexdigest()[:20]}
