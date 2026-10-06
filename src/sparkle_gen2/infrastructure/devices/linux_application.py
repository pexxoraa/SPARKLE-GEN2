from __future__ import annotations
import hashlib,json,os,platform,re,shutil,signal,stat,subprocess,time
from dataclasses import asdict,dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

MAX_ARGS=8
MAX_ARG_CHARS=256
MAX_COMMAND_BYTES=2048
MAX_TIMEOUT_SECONDS=10
MAX_OUTPUT_BYTES=16384
MAX_OUTPUT_LINES=200
MAX_DIRECTORY_ENTRIES=100
MAX_CONTROL_ACTIONS=4
SAFE_ENV={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C'}
SHELL_META=re.compile(r'[;&|`$<>\n\r\x00]')
SENSITIVE_COMPONENTS=frozenset({'.ssh','.gnupg','.aws','.kube','.docker','.config','.git','credentials','secrets'})

class LinuxApplicationError(RuntimeError):
    def __init__(self,category:str,message:str):super().__init__(message);self.category=category

@dataclass(frozen=True,slots=True)
class LinuxCommand:
    executable:str;arguments:tuple[str,...]=();working_directory:str|None=None;timeout_seconds:int=5
    def normalized(self):return {'executable':self.executable,'arguments':list(self.arguments),'working_directory':self.working_directory,'timeout_seconds':self.timeout_seconds}
    def digest(self):return hashlib.sha256(json.dumps(self.normalized(),sort_keys=True,separators=(',',':')).encode()).hexdigest()

@dataclass(frozen=True,slots=True)
class LinuxInspectionResult:
    kind:str;data:dict[str,Any];command_digest:str|None;truncated:bool=False
    def to_dict(self):return asdict(self)

@dataclass(frozen=True,slots=True)
class LinuxExecutionResult:
    action:str;application:str;process_reference:str;started:bool;command_digest:str
    def to_dict(self):return asdict(self)

class LinuxApplicationAdapter:
    provider='SPARKLE bounded Linux application boundary'
    _FIXED_COMMANDS={
        'cwd':(('/bin/pwd','/usr/bin/pwd'),()),
        'os':(('/usr/bin/uname','/bin/uname'),('-s','-r','-m')),
        'identity':(('/usr/bin/id','/bin/id'),()),
        'disk':(('/bin/df','/usr/bin/df'),('-Pk',)),
        'memory':(('/usr/bin/free','/bin/free'),('-b',)),
    }
    _CONTROL_COMMANDS={'sleep_probe':(('/usr/bin/sleep','/bin/sleep'),)}
    def __init__(self,*,owner_user_id='user',device_id=None,allowed_roots=None,runner=None,popen_factory=None):
        if platform.system().lower()!='linux':raise LinuxApplicationError('UNAVAILABLE','Linux adapter requires Linux')
        self.owner_user_id=owner_user_id;self.device_id=device_id or self._device_identity();root=Path(__file__).resolve().parents[2]
        self.allowed_roots=tuple(self._canonical_root(x) for x in (allowed_roots or [root]));self._runner=runner or subprocess.run;self._popen=popen_factory or subprocess.Popen;self._closed=False;self._control_count=0;self._active=None
    @staticmethod
    def _device_identity():
        raw=None
        for p in ('/etc/machine-id','/var/lib/dbus/machine-id'):
            try:
                v=Path(p).read_text(encoding='ascii').strip().lower()
                if re.fullmatch(r'[0-9a-f]{32}',v):raw=v;break
            except Exception:pass
        if raw is None:raw=platform.node()+'\0'+platform.machine()
        return 'linux-device:'+hashlib.sha256(('SPARKLE-LINUX/1\0'+raw).encode()).hexdigest()[:32]
    @staticmethod
    def _canonical_root(value):
        p=Path(value).expanduser().resolve(strict=True)
        if not p.is_dir():raise ValueError('Linux allowed root must be a directory')
        return p
    @staticmethod
    def _resolve_executable(candidates):
        for raw in candidates:
            p=Path(raw)
            try:r=p.resolve(strict=True)
            except OSError:continue
            if r.is_file() and os.access(r,os.X_OK):return str(r)
        raise LinuxApplicationError('EXECUTOR_UNAVAILABLE','required allowlisted executable is unavailable')
    @classmethod
    def _command(cls,kind,*,working_directory=None,timeout_seconds=5,extra_args=()):
        if kind not in cls._FIXED_COMMANDS:raise PermissionError('linux_command_not_allowlisted')
        candidates,args=cls._FIXED_COMMANDS[kind];return LinuxCommand(cls._resolve_executable(candidates),tuple(args)+tuple(extra_args),working_directory,timeout_seconds)
    @staticmethod
    def _validate_command(command:LinuxCommand,allowed_execs:set[str]):
        if command.executable not in allowed_execs:raise PermissionError('linux_executable_not_allowlisted')
        if isinstance(command.timeout_seconds,bool) or not isinstance(command.timeout_seconds,int) or not 1<=command.timeout_seconds<=MAX_TIMEOUT_SECONDS:raise ValueError('linux timeout out of bounds')
        if len(command.arguments)>MAX_ARGS:raise ValueError('linux argument count exceeds bound')
        total=len(command.executable.encode())
        for arg in command.arguments:
            if not isinstance(arg,str) or len(arg)>MAX_ARG_CHARS or SHELL_META.search(arg):raise ValueError('linux argument is invalid')
            total+=len(arg.encode())+1
        if total>MAX_COMMAND_BYTES:raise ValueError('linux command size exceeds bound')
    @staticmethod
    def _bounded(data:bytes):
        clipped=data[:MAX_OUTPUT_BYTES];text=clipped.decode('utf-8','replace');lines=text.splitlines();truncated=len(data)>MAX_OUTPUT_BYTES or len(lines)>MAX_OUTPUT_LINES
        if len(lines)>MAX_OUTPUT_LINES:text='\n'.join(lines[:MAX_OUTPUT_LINES])
        return text.strip(),truncated
    def _allowed_execs(self):
        out=set()
        for candidates,_ in self._FIXED_COMMANDS.values():out.add(self._resolve_executable(candidates))
        for (candidates,) in self._CONTROL_COMMANDS.values():out.add(self._resolve_executable(candidates))
        return out
    def _run(self,command:LinuxCommand):
        self._validate_command(command,self._allowed_execs())
        try:
            cp=self._runner([command.executable,*command.arguments],cwd=command.working_directory,env=dict(SAFE_ENV),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=command.timeout_seconds,check=False)
        except subprocess.TimeoutExpired as exc:raise LinuxApplicationError('TIMEOUT','Linux command timed out') from exc
        except Exception as exc:raise LinuxApplicationError('EXECUTION_FAILED','Linux command execution failed') from exc
        stdout,tr1=self._bounded(bytes(cp.stdout or b''));stderr,tr2=self._bounded(bytes(cp.stderr or b''))
        if cp.returncode!=0:raise LinuxApplicationError('EXECUTION_FAILED','allowlisted Linux command returned failure')
        return stdout,stderr,tr1 or tr2
    def _resolve_user_path(self,raw):
        if raw is None or raw in {'','.','workspace'}:candidate=self.allowed_roots[0]
        else:
            if not isinstance(raw,str) or len(raw)>1024 or '\x00' in raw:raise ValueError('Linux path is invalid')
            decoded=unquote(raw)
            if decoded!=raw and ('..' in decoded.split('/') or decoded.startswith('/')):raise PermissionError('linux_encoded_path_traversal_denied')
            p=Path(raw)
            if p.is_absolute() or '..' in p.parts:raise PermissionError('linux_path_escape_denied')
            if any(part.lower() in SENSITIVE_COMPONENTS for part in p.parts):raise PermissionError('linux_sensitive_path_denied')
            candidate=self.allowed_roots[0]/p
        try:resolved=candidate.resolve(strict=True)
        except OSError as exc:raise PermissionError('linux_path_unavailable') from exc
        if not any(resolved==root or root in resolved.parents for root in self.allowed_roots):raise PermissionError('linux_path_outside_allowed_roots')
        # The requested path itself may not be a symlink, even if it resolves inside the root.
        try:
            if candidate.is_symlink():raise PermissionError('linux_symlink_path_denied')
        except OSError as exc:raise PermissionError('linux_path_unavailable') from exc
        return resolved
    def configured(self):return not self._closed and platform.system().lower()=='linux'
    @property
    def bound_device_id(self):return self.device_id
    def authorize(self):
        if not self.configured():raise LinuxApplicationError('UNAVAILABLE','Linux execution boundary is closed')
        return {'authorization_reference':'linux-local:'+hashlib.sha256(self.device_id.encode()).hexdigest()[:20],'granted_scopes':['linux.inspect','linux.execute'],'device_id':self.device_id}
    def health(self):
        try:
            if self._closed:return {'ok':False,'status':'UNAVAILABLE','authorization_state':'REVOKED','provider':self.provider,'device_id':self.device_id}
            required=[self._resolve_executable(c) for c,_ in self._FIXED_COMMANDS.values()];ok=all(Path(x).is_file() and os.access(x,os.X_OK) for x in required)
            return {'ok':ok,'status':'HEALTHY' if ok else 'UNAVAILABLE','authorization_state':'AUTHORIZED' if ok else 'FAILED','provider':self.provider,'device_id':self.device_id,'allowed_root_hashes':[hashlib.sha256(str(x).encode()).hexdigest()[:20] for x in self.allowed_roots],'control_actions':['launch_sleep_probe']}
        except Exception:return {'ok':False,'status':'UNAVAILABLE','authorization_state':'FAILED','provider':self.provider,'device_id':self.device_id}
    def _binding(self,owner_user_id,device_id):
        if owner_user_id!=self.owner_user_id:raise PermissionError('linux_owner_mismatch')
        if device_id!=self.device_id:raise PermissionError('linux_device_mismatch')
        if self._closed:raise PermissionError('linux_executor_revoked')
    def _inspect(self,p):
        if set(p)-{'kind','path','timeout_seconds'}:raise ValueError('unsupported linux.inspect argument')
        kind=p.get('kind');timeout=p.get('timeout_seconds',5)
        if kind not in {'cwd','os','identity','disk','memory','list_directory'}:raise PermissionError('linux_inspection_not_allowlisted')
        if kind=='list_directory':
            path=self._resolve_user_path(p.get('path'));entries=[]
            if not path.is_dir():raise ValueError('Linux list_directory requires a directory')
            visible=[child for child in sorted(path.iterdir(),key=lambda x:x.name) if child.name.lower() not in SENSITIVE_COMPONENTS]
            for child in visible[:MAX_DIRECTORY_ENTRIES]:
                try:st=child.lstat();typ='symlink' if stat.S_ISLNK(st.st_mode) else ('directory' if stat.S_ISDIR(st.st_mode) else 'file')
                except OSError:continue
                entries.append({'name':child.name[:255],'type':typ})
            total=len(visible);data={'entry_count':len(entries),'entries':entries,'truncated':total>MAX_DIRECTORY_ENTRIES,'path_reference':'allowed-root:'+hashlib.sha256(str(path).encode()).hexdigest()[:20]}
            data['relative_path']='.' if path==self.allowed_roots[0] else str(path.relative_to(self.allowed_roots[0]));return LinuxInspectionResult(kind,data,None,total>MAX_DIRECTORY_ENTRIES).to_dict()
        work=str(self.allowed_roots[0]);extra=()
        if kind=='disk':extra=(work,)
        cmd=self._command(kind,working_directory=work,timeout_seconds=timeout,extra_args=extra);stdout,_stderr,truncated=self._run(cmd)
        if kind=='cwd':data={'cwd_reference':'allowed-root:'+hashlib.sha256(stdout.encode()).hexdigest()[:20]}
        elif kind=='os':
            parts=stdout.split();data={'system':parts[0] if parts else '', 'release':parts[1] if len(parts)>1 else '', 'machine':parts[2] if len(parts)>2 else ''}
        elif kind=='identity':
            mu=re.search(r'uid=(\d+)',stdout);mg=re.search(r'gid=(\d+)',stdout)
            if mu is None or mg is None:raise LinuxApplicationError('MALFORMED_RESPONSE','id output is malformed')
            data={'uid':int(mu.group(1)),'gid':int(mg.group(1))}
        elif kind=='disk':
            lines=stdout.splitlines();fields=lines[-1].split() if lines else []
            if len(fields)<6:raise LinuxApplicationError('MALFORMED_RESPONSE','df output is malformed')
            data={'total_bytes':int(fields[1])*1024,'used_bytes':int(fields[2])*1024,'available_bytes':int(fields[3])*1024,'capacity_percent':fields[4]}
        else:
            lines=[x.split() for x in stdout.splitlines() if x.strip()];mem=next((x for x in lines if x and x[0].lower().startswith('mem:')),None)
            if mem is None or len(mem)<4:raise LinuxApplicationError('MALFORMED_RESPONSE','free output is malformed')
            data={'total_bytes':int(mem[1]),'used_bytes':int(mem[2]),'available_bytes':int(mem[-1])}
        return LinuxInspectionResult(kind,data,cmd.digest(),truncated).to_dict()
    def _execute(self,p):
        if set(p)-{'action','duration_seconds'}:raise ValueError('unsupported linux.execute argument')
        if p.get('action')!='launch_sleep_probe':raise PermissionError('linux_control_action_not_allowlisted')
        duration=p.get('duration_seconds',3)
        if isinstance(duration,bool) or not isinstance(duration,int) or not 2<=duration<=5:raise ValueError('linux control duration must be 2..5 seconds')
        if self._control_count>=MAX_CONTROL_ACTIONS:raise LinuxApplicationError('CONTROL_LIMIT','Linux control action limit reached')
        if self._active is not None and self._active.poll() is None:raise LinuxApplicationError('CONTROL_BUSY','a controlled Linux process is already active')
        executable=self._resolve_executable(self._CONTROL_COMMANDS['sleep_probe'][0]);cmd=LinuxCommand(executable,(str(duration),),str(self.allowed_roots[0]),duration+2);self._validate_command(cmd,self._allowed_execs())
        try:proc=self._popen([cmd.executable,*cmd.arguments],cwd=cmd.working_directory,env=dict(SAFE_ENV),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        except Exception as exc:raise LinuxApplicationError('EXECUTION_FAILED','approved Linux application failed to launch') from exc
        self._active=proc;self._control_count+=1;ref='linux-process:'+hashlib.sha256((self.device_id+'\0'+str(proc.pid)+'\0'+cmd.digest()).encode()).hexdigest()[:24]
        return LinuxExecutionResult('launch_sleep_probe','sleep_probe',ref,proc.poll() is None,cmd.digest()).to_dict()
    def invoke_with_context(self,operation,payload,*,owner_user_id=None,device_id=None,**_context):
        self._binding(owner_user_id,device_id);p=dict(payload or {})
        if operation=='inspect':result=self._inspect(p);return {'provider':self.provider,'operation':operation,'device_reference':hashlib.sha256(self.device_id.encode()).hexdigest()[:20],'result':result,'provider_reference':'linux:'+str(result.get('command_digest') or hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest())[:24]}
        if operation=='execute':result=self._execute(p);return {'provider':self.provider,'operation':operation,'device_reference':hashlib.sha256(self.device_id.encode()).hexdigest()[:20],'result':result,'provider_reference':result['process_reference']}
        raise KeyError(operation)
    def invoke(self,operation,payload):return self.invoke_with_context(operation,payload,owner_user_id=self.owner_user_id,device_id=self.device_id)
    @staticmethod
    def _digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    def _verify_inspect(self,result):
        value=result.get('result') if isinstance(result,dict) else None
        if not isinstance(value,dict):return {'verified':False,'reason':'inspection_result_missing','method':'independent OS reread'}
        kind=value.get('kind');data=value.get('data')
        if not isinstance(data,dict):return {'verified':False,'reason':'inspection_data_missing','method':'independent OS reread'}
        try:
            if kind=='cwd':ok=data.get('cwd_reference')=='allowed-root:'+hashlib.sha256(str(self.allowed_roots[0]).encode()).hexdigest()[:20]
            elif kind=='os':
                u=platform.uname();ok=data.get('system')==u.system and data.get('release')==u.release and data.get('machine')==u.machine
            elif kind=='identity':ok=data.get('uid')==os.getuid() and data.get('gid')==os.getgid()
            elif kind=='disk':
                du=shutil.disk_usage(self.allowed_roots[0]);reported=int(data.get('total_bytes',-1));ok=reported>0 and abs(reported-du.total)<=max(4096,int(du.total*.01)) and int(data.get('available_bytes',-1))>=0
            elif kind=='memory':
                page=os.sysconf('SC_PAGE_SIZE');total=os.sysconf('SC_PHYS_PAGES')*page;rt=int(data.get('total_bytes',-1));ra=int(data.get('available_bytes',-1));ru=int(data.get('used_bytes',-1));ok=rt>0 and abs(rt-total)<=max(page,int(total*.01)) and 0<=ra<=rt and 0<=ru<=rt
            elif kind=='list_directory':
                relative=data.get('relative_path');path=self._resolve_user_path(relative)
                expected_ref='allowed-root:'+hashlib.sha256(str(path).encode()).hexdigest()[:20]
                if data.get('path_reference')!=expected_ref:return {'verified':False,'reason':'directory_reference_mismatch','method':'independent directory reread'}
                names=[x.name[:255] for x in sorted(path.iterdir(),key=lambda x:x.name) if x.name.lower() not in SENSITIVE_COMPONENTS][:MAX_DIRECTORY_ENTRIES];ok=names==[x.get('name') for x in data.get('entries',[])]
            else:return {'verified':False,'reason':'unsupported_inspection_kind','method':'independent OS reread'}
            return {'verified':bool(ok),'method':'independent Python OS state reread','kind':kind,'state_sha256':self._digest(data),'device_reference':hashlib.sha256(self.device_id.encode()).hexdigest()[:20]}
        except Exception:return {'verified':False,'reason':'inspection_reread_failed','method':'independent OS reread'}
    def _cleanup_active(self):
        proc=self._active
        if proc is None:return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill();proc.wait(timeout=2)
        finally:self._active=None
    def verify_with_context(self,operation,result,*,owner_user_id=None,**_context):
        if owner_user_id!=self.owner_user_id:return {'verified':False,'reason':'linux_owner_mismatch','method':'owner/device bound Linux verifier'}
        if not isinstance(result,dict) or result.get('provider')!=self.provider or result.get('operation')!=operation:return {'verified':False,'reason':'provider_or_operation_mismatch','method':'Linux verifier'}
        if operation=='inspect':return self._verify_inspect(result)
        if operation=='execute':
            value=result.get('result') or {};proc=self._active
            try:
                alive=proc is not None and proc.poll() is None
                if alive:
                    try:os.kill(proc.pid,0);postcondition=True
                    except OSError:postcondition=False
                else:postcondition=False
                verified=bool(value.get('started') is True and postcondition and isinstance(value.get('command_digest'),str))
                return {'verified':verified,'method':'approved launch + independent process liveness postcondition + controlled cleanup','application':'sleep_probe','process_reference':value.get('process_reference'),'command_digest':value.get('command_digest'),'executable_identity':hashlib.sha256(self._resolve_executable(self._CONTROL_COMMANDS['sleep_probe'][0]).encode()).hexdigest(),'device_reference':hashlib.sha256(self.device_id.encode()).hexdigest()[:20]}
            finally:self._cleanup_active()
        return {'verified':False,'reason':'unsupported_operation','method':'Linux verifier'}
    def verify(self,operation,result):return self.verify_with_context(operation,result,owner_user_id=self.owner_user_id)
    def close(self):
        self._cleanup_active();self._closed=True;return {'status':'closed','device_reference':hashlib.sha256(self.device_id.encode()).hexdigest()[:20]}
