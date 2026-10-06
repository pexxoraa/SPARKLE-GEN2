"""Command-line interface. Business logic lives outside this module."""

from __future__ import annotations
import argparse,json,sys
from ..runtime import build_components


def normalize_request(parts):
    values=list(parts)
    if values and values[0]=='chat':
        values=values[1:]
    return ' '.join(values).strip()


def format_result(result,verbose=False):
    if not verbose:
        return result['text']
    lines=[]
    if result.get('checked'):
        lines.append('I checked:'); lines.extend(f"• {x}" for x in result['checked'])
    if result.get('verified'):
        lines.append('I completed:'); lines.extend(f"• {x}" for x in result['verified'])
    approvals=list(result.get('approvals',[]))+list(result.get('gen1_approvals',[]))
    if approvals:
        lines.append('I need approval for:'); lines.extend(f"• {x}" for x in approvals)
    if result.get('status') not in {'COMPLETED','CANCELLED'}:
        lines.extend(['Next:','• resume verified remaining work when its gate is satisfied'])
    if result.get('trace_id'):lines.append(f"Trace: {result['trace_id']}")
    lines.append(result['text'])
    return '\n'.join(lines)


def build_parser():
    parser=argparse.ArgumentParser(prog='sparkle')
    parser.add_argument('request',nargs='*')
    actions=parser.add_mutually_exclusive_group()
    actions.add_argument('--resume'); actions.add_argument('--approve'); actions.add_argument('--reject'); actions.add_argument('--cancel')
    parser.add_argument('--session'); parser.add_argument('--json',action='store_true'); parser.add_argument('--verbose',action='store_true')
    return parser


def entrypoint(argv=None):
    args=build_parser().parse_args(argv)
    store,agent,sessions=build_components(activate_external_connectors=True)
    if args.approve or args.reject:
        result=agent.decide_approval(args.approve or args.reject,'approve' if args.approve else 'reject')
    elif args.cancel: result=agent.cancel(args.cancel)
    elif args.resume: result=agent.resume(args.resume)
    else:
        request=normalize_request(args.request)
        if not request and sys.stdin.isatty():request=input('SPARKLE> ').strip()
        if not request:raise SystemExit('provide a request, --resume, --cancel, --approve, or --reject')
        result=agent.start(request)
    if args.session and 'goal_id' in result:
        try:sessions.attach_goal(args.session,result['goal_id'])
        except KeyError:result['session_id']=sessions.create(result['goal_id']).session_id
    print(json.dumps(result,indent=2) if args.json else format_result(result,args.verbose))
    closer=getattr(getattr(agent,'connectors',None),'close',None)
    if callable(closer):closer()
    return 0


if __name__=='__main__':entrypoint()
