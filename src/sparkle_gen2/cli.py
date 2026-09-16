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
    p=argparse.ArgumentParser(prog="sparkle-gen2"); p.add_argument("request",nargs="*"); p.add_argument("--resume"); p.add_argument("--json",action="store_true"); a=p.parse_args()
    agent=build_agent(); result=agent.resume(a.resume) if a.resume else agent.start(" ".join(a.request))
    print(json.dumps(result,indent=2) if a.json else result["text"])
if __name__=="__main__": entrypoint()
