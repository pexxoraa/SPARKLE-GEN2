from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Protocol

@dataclass(slots=True)
class ToolObservation:
    ok:bool; tool:str; output:dict[str,Any]; verification:dict[str,Any]
    requires_approval:bool=False; approval_id:str|None=None

class Gen1Gateway(Protocol):
    def retrieve_context(self,request:str,requirements:list[str])->dict[str,Any]: ...
    def invoke(self,tool:str,arguments:dict[str,Any])->ToolObservation: ...
    def health(self)->dict[str,Any]: ...

class LocalGen1Gateway:
    def __init__(self,system=None):
        if system is None:
            from sparkle.system import SparkleSystem
            system=SparkleSystem()
        self.system=system
    def health(self)->dict[str,Any]:
        return {"available":True,"tools":sorted(self.system.tools.names),"boundary":"SparkleSystem/ToolRegistry"}
    def retrieve_context(self,request:str,requirements:list[str])->dict[str,Any]:
        bundle=self.system.context.build(request)
        return {"requirements":list(requirements),"rendered":bundle.render()[:12000],"source":"gen1-context"}
    def invoke(self,tool:str,arguments:dict[str,Any])->ToolObservation:
        if tool not in self.system.tools.names:
            return ToolObservation(False,tool,{"error":"tool unavailable"},{"verified":False,"reason":"not_registered"})
        try: output=self.system.tools.execute(tool,arguments,allowed={tool})
        except Exception as exc:
            return ToolObservation(False,tool,{"error":str(exc),"error_type":type(exc).__name__},{"verified":False,"reason":"execution_failed"})
        if not isinstance(output,dict): output={"value":output}
        if tool=="memory_write" and output.get("status")=="pending":
            pid=output.get("proposal_id"); verified=False
            if isinstance(pid,str) and hasattr(self.system,"memory_review"):
                verified=any(r.get("id")==pid for r in self.system.memory_review.list(limit=100,status="pending"))
            return ToolObservation(True,tool,output,{"verified":verified,"method":"re-read pending memory proposal"},True,pid)
        return ToolObservation(True,tool,output,{"verified":True,"method":"tool result contract; no durable state assertion"})
