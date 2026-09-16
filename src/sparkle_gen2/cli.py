from __future__ import annotations
import argparse,json,os,sys
from pathlib import Path
from .core import PersonalAgent
from .connector_catalog import build_default_connectors
from .context_sources import PersonalContextAssembler
from .devices import DeviceManager
from .gen1 import LocalGen1Gateway
from .sessions import SessionService
from .personal_data import PersonalDataOrchestrator
from .world_model import WorldModel
from .storage import Gen2Store
from .environment_gateway import load_environment_gateway

def data_path()->Path:
    return Path(os.environ.get('SPARKLE_GEN2_DB',Path.home()/'.local'/'share'/'sparkle-gen2'/'gen2.sqlite3'))
def build_components():
    store=Gen2Store(data_path());gen1=LocalGen1Gateway();environment_config=Path(os.environ.get('SPARKLE_GEN2_ENVIRONMENT_CONFIG',Path.home()/'.config'/'sparkle-gen2'/'environment.json'));gen1=load_environment_gateway(gen1,environment_config);context=PersonalContextAssembler(personal_data=PersonalDataOrchestrator(gen1),connectors=build_default_connectors(),store=store,devices=DeviceManager(),world=WorldModel(store))
    return store,PersonalAgent(store,gen1,context_provider=context),SessionService(store)
def normalize_request(parts):
    values=list(parts)
    if values and values[0]=='chat':values=values[1:]
    return ' '.join(values).strip()
def format_result(result,verbose=False):
    if not verbose:return result['text']
    lines=[];checked=list(result.get('checked',[]));completed=list(result.get('verified',[]));approvals=list(result.get('approvals',[]));gen1=list(result.get('gen1_approvals',[]))
    if checked:lines.append('I checked:');lines.extend(f'• {x}' for x in checked)
    if completed:lines.append('I completed:');lines.extend(f'• {x}' for x in completed)
    if approvals or gen1:
        lines.append('I need approval for:');lines.extend(f'• Gen-2 approval {x}' for x in approvals);lines.extend(f'• Gen-1 approval {x}' for x in gen1)
    if result.get('status') not in {'COMPLETED','CANCELLED'}:lines.extend(['Next:','• resume verified remaining work when its gate is satisfied'])
    if result.get('trace_id'):lines.append(f"Trace: {result['trace_id']}")
    lines.append(result['text']);return '\n'.join(lines)
def entrypoint(argv=None):
    p=argparse.ArgumentParser(prog='sparkle')
    p.add_argument('request',nargs='*');p.add_argument('--resume');p.add_argument('--approve');p.add_argument('--reject');p.add_argument('--cancel')
    p.add_argument('--session');p.add_argument('--json',action='store_true');p.add_argument('--verbose',action='store_true')
    a=p.parse_args(argv);store,agent,sessions=build_components()
    if a.approve or a.reject:
        result=agent.decide_approval(a.approve or a.reject,'approve' if a.approve else 'reject');text=f"Approval {result['status'].lower()}: {result['approval_id']}"
        print(json.dumps(result,indent=2) if a.json else text);return 0
    if a.cancel: result=agent.cancel(a.cancel)
    elif a.resume: result=agent.resume(a.resume)
    else:
        request=normalize_request(a.request)
        if not request and sys.stdin.isatty():request=input('SPARKLE> ').strip()
        if not request:p.error('provide a request, `chat` request, --resume, --cancel, --approve, or --reject')
        result=agent.start(request)
    if a.session:
        try:sessions.attach_goal(a.session,result['goal_id'])
        except KeyError:
            s=sessions.create(result['goal_id'])
            if a.verbose:result['session_id']=s.session_id
    print(json.dumps(result,indent=2) if a.json else format_result(result,a.verbose));return 0
if __name__=='__main__':entrypoint()
