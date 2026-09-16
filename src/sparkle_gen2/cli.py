from __future__ import annotations
import argparse,json,os,sys
from pathlib import Path
from .core import PersonalAgent
from .gen1 import LocalGen1Gateway
from .sessions import SessionService
from .storage import Gen2Store

def data_path()->Path:
    return Path(os.environ.get('SPARKLE_GEN2_DB',Path.home()/'.local'/'share'/'sparkle-gen2'/'gen2.sqlite3'))
def build_components():
    store=Gen2Store(data_path());return store,PersonalAgent(store,LocalGen1Gateway()),SessionService(store)
def normalize_request(parts):
    values=list(parts)
    if values and values[0]=='chat':values=values[1:]
    return ' '.join(values).strip()
def format_result(result,verbose=False):
    lines=[]
    if verbose:
        for item in result.get('verified',[]):lines.append(f'✓ {item}')
        if result.get('approvals'):lines.append(f"→ Approval required: {result['approvals'][-1]}")
        if result.get('gen1_approvals'):lines.append(f"→ Gen-1 approval required: {result['gen1_approvals'][-1]}")
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
