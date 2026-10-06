from __future__ import annotations
import os,re,ssl,stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

VOICECHAT_SECRET_REF='NEMOTRON_VOICECHAT_API_KEY'
GEMINI_SECRET_REF='GEMINI_API_KEY'
NVIDIA_SECRET_REFS=('NVIDIA_API_KEY','SPARKLE_LLM_API_KEY')
VOICE_PROVIDER_SETTING='VOICE_PROVIDER'
DEFAULT_PROTECTED_CONFIG=Path.home()/'.config'/'sparkle'/'gen2.env'
_ALLOWED_REFS=frozenset({VOICECHAT_SECRET_REF,GEMINI_SECRET_REF,*NVIDIA_SECRET_REFS})
_ALLOWED_SETTINGS=frozenset({VOICE_PROVIDER_SETTING})
_NAME=re.compile(r'^[A-Z][A-Z0-9_]{1,127}$')

PROTECTED_CONFIG_ROOT=Path.home()/'.config'/'sparkle'
PROTECTED_FILE_REFS={
    'SPARKLE_GMAIL_TOKEN_FILE':('google','gmail-token.json'),
    'SPARKLE_CALENDAR_TOKEN_FILE':('google','calendar-token.json'),
    'SPARKLE_DRIVE_TOKEN_FILE':('google','drive-token.json'),
    'SPARKLE_GITHUB_TOKEN_FILE':('github','github-token.json'),
}

def protected_credential_file_refs(*,root:Path|str|None=None)->dict[str,Path]:
    base=Path(root or os.environ.get('SPARKLE_CONFIG_DIR',PROTECTED_CONFIG_ROOT)).expanduser().resolve()
    out={}
    try:
        if not base.is_dir():return out
    except OSError:return out
    for ref,parts in PROTECTED_FILE_REFS.items():
        candidate=base.joinpath(*parts)
        try:
            if candidate.is_symlink() or not candidate.is_file():continue
            resolved=candidate.resolve(strict=True)
            if base!=resolved and base not in resolved.parents:continue
            st=resolved.stat();mode=stat.S_IMODE(st.st_mode);owner=(not hasattr(os,'getuid')) or st.st_uid==os.getuid()
            if not owner or (mode & 0o077)!=0:continue
            out[ref]=resolved
        except OSError:continue
    return out

@dataclass(frozen=True,slots=True)
class ProtectedSecretStatus:
    credential_reference_found:bool
    credential_file_exists:bool
    credential_permissions:str|None
    credential_value_loaded:bool
    secure_permissions:bool
    owner_matches:bool
    def to_dict(self):
        return {
            'credential_reference_found':self.credential_reference_found,
            'credential_file_exists':self.credential_file_exists,
            'credential_permissions':self.credential_permissions,
            'credential_value_loaded':self.credential_value_loaded,
            'secure_permissions':self.secure_permissions,
            'owner_matches':self.owner_matches,
        }

def _parse_env_file(path:Path)->dict[str,str]:
    values={}
    with path.open('r',encoding='utf-8') as handle:
        for raw in handle:
            line=raw.strip()
            if not line or line.startswith('#') or '=' not in line:continue
            name,value=line.split('=',1);name=name.strip()
            if name.startswith('export '):name=name[7:].strip()
            if name not in (_ALLOWED_REFS|_ALLOWED_SETTINGS) or not _NAME.fullmatch(name):continue
            value=value.strip()
            if len(value)>=2 and value[0]==value[-1] and value[0] in {'"',"'"}:value=value[1:-1]
            if value and '\x00' not in value and '\n' not in value and '\r' not in value:values[name]=value
    return values

def protected_gen2_environment(*,base:Mapping[str,str]|None=None,path:Path|None=None)->tuple[dict[str,str],dict[str,ProtectedSecretStatus]]:
    env=dict(os.environ if base is None else base);target=Path(path or DEFAULT_PROTECTED_CONFIG).expanduser()
    exists=target.is_file();mode=None;secure=False;owner=False;values={}
    if exists:
        st=target.stat();mode=stat.S_IMODE(st.st_mode);secure=(mode & 0o077)==0;owner=(not hasattr(os,'getuid')) or st.st_uid==os.getuid()
        if secure and owner:values=_parse_env_file(target)
    statuses={}
    for ref in sorted(_ALLOWED_REFS):
        found=ref in values;loaded=bool(env.get(ref))
        if not loaded and found and values.get(ref):env[ref]=values[ref];loaded=True
        statuses[ref]=ProtectedSecretStatus(found,exists,None if mode is None else oct(mode),loaded,secure,owner)
    return env,statuses

def protected_voicechat_environment(*,base:Mapping[str,str]|None=None,path:Path|None=None)->tuple[dict[str,str],ProtectedSecretStatus]:
    source=dict(os.environ if base is None else base);env,statuses=protected_gen2_environment(base=source,path=path)
    # Preserve the narrow legacy contract: this helper exposes only VoiceChat.
    voice_env=dict(source)
    if env.get(VOICECHAT_SECRET_REF):voice_env[VOICECHAT_SECRET_REF]=env[VOICECHAT_SECRET_REF]
    for ref in (*NVIDIA_SECRET_REFS,GEMINI_SECRET_REF):voice_env.pop(ref,None)
    return voice_env,statuses[VOICECHAT_SECRET_REF]

def protected_gemini_environment(*,base:Mapping[str,str]|None=None,path:Path|None=None)->tuple[dict[str,str],ProtectedSecretStatus]:
    source=dict(os.environ if base is None else base);env,statuses=protected_gen2_environment(base=source,path=path)
    gemini_env=dict(source)
    if env.get(GEMINI_SECRET_REF):gemini_env[GEMINI_SECRET_REF]=env[GEMINI_SECRET_REF]
    for ref in (VOICECHAT_SECRET_REF,*NVIDIA_SECRET_REFS):gemini_env.pop(ref,None)
    return gemini_env,statuses[GEMINI_SECRET_REF]

def protected_voice_provider(*,base:Mapping[str,str]|None=None,path:Path|None=None)->str|None:
    from .voice_providers import normalize_voice_provider
    source=dict(os.environ if base is None else base)
    if source.get(VOICE_PROVIDER_SETTING):
        return normalize_voice_provider(source[VOICE_PROVIDER_SETTING])
    target=Path(path or DEFAULT_PROTECTED_CONFIG).expanduser()
    try:
        if target.is_symlink() or not target.is_file():return None
        st=target.stat();mode=stat.S_IMODE(st.st_mode);owner=(not hasattr(os,'getuid')) or st.st_uid==os.getuid()
        if not owner or (mode & 0o077)!=0:return None
        values=_parse_env_file(target)
    except OSError:return None
    return normalize_voice_provider(values.get(VOICE_PROVIDER_SETTING))

def build_gen2_secret_resolver(*,base:Mapping[str,str]|None=None,path:Path|None=None):
    from sparkle.secrets import SecretResolver
    env,_=protected_gen2_environment(base=base,path=path)
    return SecretResolver(env)
WORKER_CLIENT_CONFIG=Path.home()/'.config'/'sparkle'/'worker-client.env'
_WORKER_CONFIG_REFS=frozenset({'SPARKLE_EXTERNAL_WORKER_ENABLED','SPARKLE_EXTERNAL_WORKER_URL','SPARKLE_EXTERNAL_WORKER_ID','SPARKLE_EXTERNAL_WORKER_SIGNING_KEY_FILE','SSL_CERT_FILE'})

def protected_worker_client_config(*,path:Path|str|None=None)->dict[str,object]:
    target=Path(path or WORKER_CLIENT_CONFIG).expanduser()
    if target.is_symlink() or not target.is_file():return {'configured':False,'reason':'worker_client_config_unavailable'}
    st=target.stat();mode=stat.S_IMODE(st.st_mode);owner=(not hasattr(os,'getuid')) or st.st_uid==os.getuid()
    if not owner or (mode & 0o077)!=0:return {'configured':False,'reason':'worker_client_config_permissions'}
    values={}
    with target.open('r',encoding='utf-8') as handle:
        for raw in handle:
            line=raw.strip()
            if not line or line.startswith('#') or '=' not in line:continue
            name,value=line.split('=',1);name=name.strip()
            if name.startswith('export '):name=name[7:].strip()
            if name not in _WORKER_CONFIG_REFS:continue
            value=value.strip()
            if len(value)>=2 and value[0]==value[-1] and value[0] in {'"',"'"}:value=value[1:-1]
            if '\x00' in value or '\n' in value or '\r' in value:continue
            values[name]=value
    enabled=str(values.get('SPARKLE_EXTERNAL_WORKER_ENABLED','')).strip().lower() in {'1','true','yes','on'}
    endpoint=str(values.get('SPARKLE_EXTERNAL_WORKER_URL','')).strip();parsed=urlparse(endpoint)
    host=(parsed.hostname or '').lower();endpoint_ok=parsed.scheme=='https' and host in {'localhost','127.0.0.1','::1'} and not parsed.username and not parsed.password
    worker_id=str(values.get('SPARKLE_EXTERNAL_WORKER_ID','')).strip();worker_id_ok=bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{1,127}',worker_id))
    def safe_file(name,*,private):
        raw=str(values.get(name,'')).strip()
        if not raw:return None
        q=Path(raw).expanduser()
        try:
            if q.is_symlink() or not q.is_file():return None
            meta=q.stat();owned=(not hasattr(os,'getuid')) or meta.st_uid==os.getuid();m=stat.S_IMODE(meta.st_mode)
            if not owned or (private and (m & 0o077)!=0):return None
            return q.resolve(strict=True)
        except OSError:return None
    signing=safe_file('SPARKLE_EXTERNAL_WORKER_SIGNING_KEY_FILE',private=True);cafile=safe_file('SSL_CERT_FILE',private=False)
    configured=bool(enabled and endpoint_ok and worker_id_ok and signing and cafile)
    return {'configured':configured,'enabled':enabled,'endpoint':endpoint if endpoint_ok else None,'worker_id':worker_id if worker_id_ok else None,'signing_key_file':signing,'ca_file':cafile,'config_mode':oct(mode),'reason':None if configured else 'worker_client_configuration_incomplete'}

def build_protected_external_worker(root:Path,*,config_path:Path|str|None=None):
    cfg=protected_worker_client_config(path=config_path)
    if not cfg.get('configured'):return None
    from sparkle.external_worker import ExternalWorkerClient
    import urllib.request
    context=ssl.create_default_context(cafile=str(cfg['ca_file']))
    opener=urllib.request.build_opener(urllib.request.HTTPSHandler(context=context)).open
    return ExternalWorkerClient(root=root,enabled=True,endpoint=str(cfg['endpoint']),signing_key_file=Path(cfg['signing_key_file']),expected_worker_id=str(cfg['worker_id']),opener=opener)
def protected_worker_runtime_status(*,path:Path|str|None=None,timeout_seconds:float=5.0)->dict[str,object]:
    """Return bounded TLS-authenticated worker isolation metadata; never credentials."""
    import json,urllib.request
    cfg=protected_worker_client_config(path=path)
    if not cfg.get('configured'):
        return {'reachable':False,'ready':False,'reason':str(cfg.get('reason') or 'worker_client_unconfigured')}
    endpoint=urlparse(str(cfg['endpoint']))
    health=endpoint._replace(path='/health',query='',fragment='').geturl()
    context=ssl.create_default_context(cafile=str(cfg['ca_file']))
    request=urllib.request.Request(health,headers={'Accept':'application/json'},method='GET')
    try:
        with urllib.request.urlopen(request,context=context,timeout=max(1.0,min(float(timeout_seconds),10.0))) as response:
            raw=response.read(131073)
            if len(raw)>131072:raise ValueError('worker_health_response_too_large')
            value=json.loads(raw.decode('utf-8'))
    except Exception as exc:
        return {'reachable':False,'ready':False,'reason':type(exc).__name__}
    status=value.get('status') if isinstance(value,dict) else None
    if not isinstance(status,dict):return {'reachable':True,'ready':False,'reason':'worker_health_schema_invalid'}
    executor=status.get('executor') if isinstance(status.get('executor'),dict) else {}
    canaries=executor.get('canaries') if isinstance(executor.get('canaries'),dict) else {}
    expected={'host_filesystem_read','host_filesystem_write','workspace_escape','secret_environment','prohibited_network','host_process_access','artifact_modification'}
    safe_canaries={str(k):bool(v) for k,v in canaries.items() if str(k) in expected}
    return {
        'reachable':True,
        'ready':bool(value.get('ok') and status.get('ready')),
        'worker_id':str(status.get('worker_id') or '')[:128],
        'transport_security':str(status.get('transport_security') or '')[:64],
        'direct_tls':bool(status.get('direct_tls')),
        'credentials_exposed':bool(status.get('credentials_exposed')),
        'executor_mode':str(executor.get('mode') or '')[:64],
        'preflight_passed':bool(executor.get('preflight_passed')),
        'filesystem_isolation':bool(executor.get('filesystem_isolation')),
        'network_isolation':bool(executor.get('network_isolation')),
        'ephemeral_workspace':bool(executor.get('ephemeral_workspace')),
        'resource_limits':bool(executor.get('resource_limits')),
        'unsafe_process_mode':bool(executor.get('unsafe_process_mode')),
        'hostile_canaries_passed':bool(executor.get('hostile_canaries_passed')),
        'preflight_canary_evidence_complete':bool(executor.get('preflight_canary_evidence_complete')),
        'isolation_profile':str(executor.get('isolation_profile') or '')[:128],
        'canaries':safe_canaries,
    }

