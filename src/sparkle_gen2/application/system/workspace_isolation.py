from __future__ import annotations
import base64,hashlib,json,os,re,subprocess,tempfile,time,uuid
from pathlib import Path
from typing import Any

from sparkle.builders import WorkspaceManager
from sparkle.external_worker import ExternalWorkerClient
from sparkle.worker_executor import BubblewrapExecutor,WorkerJob,WorkerSourceFile

WORKER_ID_PREFIX='sparkle-gen2-strict-'
PROFILE='SPARKLE-GEN2-WORKSPACE-STRICT/1'

class StrictBubblewrapExecutor(BubblewrapExecutor):
    """Gen-2 hardening of the certified fixed unittest Bubblewrap executor.

    Runtime libraries are read-only, the namespace root is read-only, and only the
    disposable workspace copy is writable. No shell or arbitrary command is exposed.
    """
    ISOLATION_PROFILE=PROFILE

    def _base_command(self,project:Path)->list[str]:
        if not self.bubblewrap_binary or not self._SAFE_BINARY.fullmatch(self.bubblewrap_binary):
            raise RuntimeError('Bubblewrap executable is unavailable')
        command=[self.bubblewrap_binary,'--die-with-parent','--new-session','--unshare-all','--clearenv','--proc','/proc','--dir','/workspace','--dir','/opt','--dir','/opt/sparkle','--ro-bind',str(self.runner_script),'/opt/sparkle/sandbox_runner.py']
        for root in self._runtime_mounts():command.extend(['--ro-bind',str(root),str(root)])
        ld_cache=Path('/etc/ld.so.cache')
        if ld_cache.is_file():command.extend(['--dir','/etc','--ro-bind',str(ld_cache),str(ld_cache)])
        # Freeze every namespace-root path, then add exactly one writable mount.
        command.extend(['--remount-ro','/','--bind',str(project),'/workspace','--chdir','/workspace','--setenv','PATH',str(Path(self.python_binary).parent)+':/usr/bin:/bin','--setenv','LANG','C.UTF-8','--setenv','LC_ALL','C.UTF-8','--setenv','PYTHONHASHSEED','0','--setenv','PYTHONDONTWRITEBYTECODE','1','--setenv','SPARKLE_TEST_SANDBOX','1','--setenv','PWD','/workspace','--'])
        return command

    def _run_preflight(self)->bool:
        if os.name!='posix' or not self.bubblewrap_binary or not Path(self.bubblewrap_binary).is_file() or not Path(self.python_binary).is_file() or not self.runner_script.is_file() or not self.python_binary.startswith(('/usr/','/bin/')):
            self._failure_type='ExecutorDependencyUnavailable';self._preflight_failure_stage='dependency_validation';self._preflight_failure_reason='dependency_unavailable';return False
        probe=r'''import json,os,socket,sys
host_canary,other_workspace,artifact_canary,allowed_raw,host_pid=sys.argv[1:]
allowed=set(allowed_raw.split(','));results={}
results['host_filesystem_read']=not os.path.exists(host_canary) and not os.path.exists('/etc/passwd') and not os.path.exists('/home')
blocked=True
for path in ('/outside-write','/etc/outside-write',host_canary,'/proc/1/root'+host_canary):
    try:
        with open(path,'wb') as h:h.write(b'x')
    except OSError:pass
    else:blocked=False
results['host_filesystem_write']=blocked
results['workspace_escape']=not os.path.exists(other_workspace)
results['secret_environment']=set(os.environ)==allowed and os.environ.get('PWD')=='/workspace' and all(k not in os.environ for k in ('NVIDIA_API_KEY','NEMOTRON_VOICECHAT_API_KEY','AWS_SECRET_ACCESS_KEY','GITHUB_TOKEN'))
network_blocked=True
for addr in (('1.1.1.1',53),('127.0.0.1',8770)):
    s=socket.socket();s.settimeout(.2)
    try:s.connect(addr)
    except OSError:pass
    else:network_blocked=False
    finally:s.close()
results['prohibited_network']=network_blocked
try:os.kill(int(host_pid),0)
except OSError:results['host_process_access']=len([x for x in os.listdir('/proc') if x.isdigit()])<=8
else:results['host_process_access']=False
try:
    with open(artifact_canary,'wb') as h:h.write(b'x')
except OSError:results['artifact_modification']=True
else:results['artifact_modification']=False
workspace_write=False
try:
    with open('/workspace/.strict-preflight-write','wb') as h:h.write(b'ok')
except OSError:pass
else:workspace_write=True
print(json.dumps(results,sort_keys=True,separators=(',',':')))
raise SystemExit(0 if all(results.values()) and workspace_write else 4)'''
        with tempfile.TemporaryDirectory(prefix='sparkle-g2-strict-preflight-') as directory:
            root=Path(directory);workspace=root/'workspace';workspace.mkdir(mode=0o700);canary=root/'host-canary';canary.write_text('host-only',encoding='utf-8');other=root/'other-workspace';other.mkdir(mode=0o700);artifact=root/'immutable-artifact';artifact.write_text('immutable',encoding='utf-8');artifact.chmod(0o400)
            allowed=','.join({'PATH','LANG','LC_ALL','PYTHONHASHSEED','PYTHONDONTWRITEBYTECODE','SPARKLE_TEST_SANDBOX','PWD'})
            command=self._base_command(workspace)+[self.python_binary,'-I','-c',probe,str(canary),str(other),str(artifact),allowed,str(os.getpid())]
            try:completed=self.preflight_runner(command,env={'PATH':str(Path(self.bubblewrap_binary).parent)},capture_output=True,text=True,timeout=5,check=False)
            except (OSError,subprocess.SubprocessError) as exc:self._failure_type=type(exc).__name__;self._preflight_failure_stage='subprocess_execution';self._preflight_failure_reason='subprocess_exception';return False
            self._preflight_returncode=max(-255,min(int(completed.returncode),255));artifact_unchanged=artifact.read_text(encoding='utf-8')=='immutable';outside_unchanged=not (root/'outside-write').exists()
        try:reported=json.loads(completed.stdout.strip())
        except (AttributeError,json.JSONDecodeError):reported={}
        valid=isinstance(reported,dict) and set(reported)==set(self.CANARY_NAMES) and all(isinstance(reported.get(name),bool) for name in self.CANARY_NAMES)
        self._preflight_canary_evidence_complete=valid
        if valid:self._canary_results={name:bool(reported[name]) for name in self.CANARY_NAMES}
        if completed.returncode!=0 or not valid or not all(self._canary_results.values()) or not artifact_unchanged or not outside_unchanged:
            self._failure_type='IsolationPreflightFailed';self._preflight_failure_stage='strict_canary_validation';self._preflight_failure_reason='strict_canary_failed';return False
        self._failure_type=None;self._preflight_failure_stage=None;self._preflight_failure_reason=None;return True

class StrictLocalWorkspaceWorker:
    def __init__(self,root:Path):
        self.root=Path(root).resolve();self.executor=StrictBubblewrapExecutor();self.worker_id=WORKER_ID_PREFIX+uuid.uuid4().hex;self._runs=[];self._next_id=1;self._closed=False
        self._bundler=ExternalWorkerClient(root=self.root,enabled=False)
    def status(self)->dict[str,Any]:
        ex=self.executor.status();ready=bool(ex.get('available')) and not self._closed
        return {'configured':ready,'enabled':ready,'endpoint_https_valid':True,'worker_identity_configured':True,'https_required':False,'explicit_approval_required':True,'ready':ready,'worker_id':self.worker_id,'executor':ex,'credentials_exposed':False,'isolation_verified':bool(ready and ex.get('preflight_passed') and ex.get('hostile_canaries_passed'))}
    def _bundle(self,project:Path):
        files,total,test_files=self._bundler._source_bundle(project)
        items=tuple(WorkerSourceFile(str(f['path']),base64.b64decode(f['content_base64'],validate=True),str(f['sha256'])) for f in files)
        digest=hashlib.sha256(json.dumps([(x.path,x.sha256) for x in items],separators=(',',':')).encode()).hexdigest()
        return items,total,test_files,digest
    def _run_path(self,project_name:str,project:Path,*,timeout_seconds:int=10,max_output_chars:int=ExternalWorkerClient.MAX_OUTPUT_CHARS)->dict[str,Any]:
        if self._closed:raise RuntimeError('strict workspace worker is closed')
        if not WorkspaceManager.NAME_PATTERN.fullmatch(project_name):raise ValueError('Project name must be a bounded lowercase identifier')
        if project.is_symlink() or not project.is_dir():raise ValueError('Workspace is unavailable or unsafe')
        if not isinstance(timeout_seconds,int) or isinstance(timeout_seconds,bool) or not 1<=timeout_seconds<=60:raise ValueError('timeout bound invalid')
        if not isinstance(max_output_chars,int) or isinstance(max_output_chars,bool) or not 100<=max_output_chars<=ExternalWorkerClient.MAX_OUTPUT_CHARS:raise ValueError('output bound invalid')
        items,total,test_files,digest=self._bundle(project.resolve());job=WorkerJob('SPK-G2-'+uuid.uuid4().hex.upper(),project_name,timeout_seconds,max_output_chars,items,digest,None)
        started=time.monotonic();result=self.executor.execute(job,worker_id=self.worker_id);ex=self.executor.status();isolation=bool(ex.get('preflight_passed') and ex.get('hostile_canaries_passed') and ex.get('isolation_profile')==PROFILE and all((ex.get('canaries') or {}).values()) and result.sandbox.get('filesystem_isolation') and result.sandbox.get('network_isolation'))
        row={'external_test_run_id':self._next_id,'job_id':job.job_id,'project_name':project_name,'status':'failed' if result.output_limited else result.status,'framework':'python_unittest','test_files':test_files,'returncode':result.returncode,'timed_out':result.timed_out,'output':result.output,'duration_ms':result.duration_ms,'file_count':len(items),'total_bytes':total,'response_verified':True,'sandbox_claims':dict(result.sandbox),'isolation_verified':isolation,'output_limited':bool(result.output_limited),'worker_id':self.worker_id,'isolation_evidence':{'profile_version':PROFILE,'preflight_passed':bool(ex.get('preflight_passed')),'hostile_canaries_passed':bool(ex.get('hostile_canaries_passed')),'canaries':dict(ex.get('canaries') or {})},'source_digest':digest}
        self._next_id+=1;self._runs.append(dict(row));return dict(row)
    def run(self,project_name:str)->dict[str,Any]:return self._run_path(project_name,self._bundler._project_root(project_name))
    def run_directory(self,project_name:str,workspace:Path,*,approved:bool,timeout_seconds:int=10,max_output_chars:int=ExternalWorkerClient.MAX_OUTPUT_CHARS)->dict[str,Any]:
        if approved is not True:raise PermissionError('strict workspace test requires explicit approval')
        candidate=Path(workspace)
        if candidate.is_symlink() or not candidate.is_dir():raise ValueError('Workspace is unavailable or unsafe')
        resolved=candidate.resolve();return self._run_path(project_name,resolved,timeout_seconds=timeout_seconds,max_output_chars=max_output_chars)
    def list(self,*,limit:int=20)->list[dict[str,Any]]:return [dict(x) for x in self._runs[-max(1,min(int(limit),100)):][::-1]]
    def close(self):self._closed=True;return {'status':'closed','worker_id':self.worker_id}

def build_strict_workspace_worker(root:Path):
    worker=StrictLocalWorkspaceWorker(root)
    return worker if worker.status().get('configured') else None
