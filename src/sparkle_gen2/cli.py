from __future__ import annotations
import argparse,json,os
from pathlib import Path
from .core import PersonalAgent
from .gen1 import LocalGen1Gateway
from .storage import Gen2Store

def build_agent()->PersonalAgent:
    path=Path(os.environ.get("SPARKLE_GEN2_DB",Path.home()/".local"/"share"/"sparkle-gen2"/"gen2.sqlite3"))
    return PersonalAgent(Gen2Store(path),LocalGen1Gateway())

def entrypoint():
    p=argparse.ArgumentParser(prog="sparkle-gen2")
    p.add_argument("request",nargs="*");p.add_argument("--resume");p.add_argument("--approve");p.add_argument("--reject")
    p.add_argument("--json",action="store_true");p.add_argument("--verbose",action="store_true")
    a=p.parse_args();agent=build_agent()
    if a.approve or a.reject:
        result=agent.decide_approval(a.approve or a.reject,"approve" if a.approve else "reject")
        text=f"Approval {result['status'].lower()}: {result['approval_id']}"
        print(json.dumps(result,indent=2) if a.json else text);return
    if a.resume: result=agent.resume(a.resume)
    else:
        request=" ".join(a.request).strip()
        if not request:p.error("provide a request, --resume, --approve, or --reject")
        result=agent.start(request)
    if a.json:print(json.dumps(result,indent=2))
    else:
        if a.verbose:
            for item in result.get('verified',[]):print(f"✓ {item}")
            if result.get('approvals'):print(f"→ Approval required: {result['approvals'][-1]}")
        print(result['text'])
if __name__=='__main__':entrypoint()
