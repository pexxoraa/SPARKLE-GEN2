from __future__ import annotations
from dataclasses import dataclass,asdict

@dataclass(slots=True)
class DomainRequirement:
    domain:str
    query:str
    required:bool=True
    def to_dict(self):return asdict(self)

class CrossDomainCoordinator:
    def __init__(self,readers:dict[str,object],*,max_domains:int=8):
        if not 1<=max_domains<=16:raise ValueError('max_domains out of range')
        self.readers=dict(readers);self.max_domains=max_domains
    def execute(self,requirements:list[DomainRequirement]):
        if not requirements or len(requirements)>self.max_domains:raise ValueError('cross-domain requirement bound exceeded')
        evidence=[];failures=[]
        for req in requirements:
            reader=self.readers.get(req.domain)
            if reader is None:
                if req.required:failures.append({'domain':req.domain,'reason':'unavailable'})
                continue
            try:result=reader(req.query)
            except Exception as exc:
                if req.required:failures.append({'domain':req.domain,'reason':type(exc).__name__})
                continue
            verification=result.get('verification',{}) if isinstance(result,dict) else {}
            if verification.get('verified') is not True:
                if req.required:failures.append({'domain':req.domain,'reason':'unverified'})
                continue
            evidence.append({'domain':req.domain,'query':req.query,'verification':verification,'output':result.get('output')})
        return {'status':'COMPLETE' if not failures else 'BLOCKED','evidence':evidence,'failures':failures,'verified_domains':[x['domain'] for x in evidence]}
