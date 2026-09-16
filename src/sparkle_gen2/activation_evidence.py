from __future__ import annotations
import json,os,tempfile
from pathlib import Path
from .core_time import now

def default_path()->Path:return Path.home()/'.local'/'share'/'sparkle-gen2'/'activation-evidence.json'
def load_activation_evidence(path=None):
    p=Path(path or default_path())
    if not p.exists():return {}
    data=json.loads(p.read_text());return data if isinstance(data,dict) else {}
def record_activation(capability,status,evidence,*,provider=None,environment=None,test_id=None,failure_reason=None,path=None):
    if status not in {'LIVE_VERIFIED','EXTERNALLY_BLOCKED','DEFERRED'}:raise ValueError('invalid activation status')
    p=Path(path or default_path());p.parent.mkdir(parents=True,exist_ok=True)
    data=load_activation_evidence(p);data[capability]={'status':status,'evidence':str(evidence),'provider':provider,'environment':environment,'test_id':test_id,'timestamp':now(),'failure_reason':failure_reason}
    fd,tmp=tempfile.mkstemp(prefix='.activation-',dir=p.parent,text=True)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as f:json.dump(data,f,sort_keys=True,indent=2)
        os.replace(tmp,p);os.chmod(p,0o600)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return data[capability]
