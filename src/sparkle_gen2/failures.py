from __future__ import annotations
from dataclasses import dataclass,asdict

@dataclass(slots=True)
class FailureDecision:
    category:str
    action:str
    reason:str
    retryable:bool
    def to_dict(self):return asdict(self)

class FailureClassifier:
    TRANSIENT=('timeout','temporar','unavailable','connection','rate limit','retry')
    POLICY=('approval','permission','denied','forbidden')
    VALIDATION=('unknown tool','unsupported_tool','invalid','schema','validation')
    EXTERNAL=('external_dependency','credential','oauth','device','provider')
    def classify(self,output,*,attempts:int,retry_limit:int):
        text=str(output).lower()
        if any(k in text for k in self.POLICY):return FailureDecision('POLICY','WAIT_USER',text[:160],False)
        if any(k in text for k in self.VALIDATION):return FailureDecision('VALIDATION','BLOCK',text[:160],False)
        transient=any(k in text for k in self.TRANSIENT)
        if transient and attempts<=retry_limit:return FailureDecision('TRANSIENT','RETRY',text[:160],True)
        if transient:return FailureDecision('TRANSIENT','REPLAN',text[:160],False)
        if any(k in text for k in self.EXTERNAL):return FailureDecision('EXTERNAL','WAIT_EXTERNAL',text[:160],False)
        if attempts<=retry_limit:return FailureDecision('EXECUTION','RETRY',text[:160],True)
        return FailureDecision('EXECUTION','REPLAN',text[:160],False)
