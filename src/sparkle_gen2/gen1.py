from __future__ import annotations
import json,uuid
from dataclasses import dataclass
from typing import Any,Protocol

@dataclass(slots=True)
class ToolObservation:
    ok:bool; tool:str; output:dict[str,Any]; verification:dict[str,Any]
    requires_approval:bool=False; approval_id:str|None=None

class Gen1Gateway(Protocol):
    def retrieve_context(self,request:str,requirements:list[str])->dict[str,Any]: ...
    def invoke(self,tool:str,arguments:dict[str,Any])->ToolObservation: ...
    def health(self)->dict[str,Any]: ...
    def plan(self,goal:dict[str,Any],context:dict[str,Any],available_capabilities:list[str])->dict[str,Any]: ...
    def approval_status(self,approval_id:str,tool:str)->dict[str,Any]: ...

class LocalGen1Gateway:
    def __init__(self,system=None):
        if system is None:
            from sparkle.system import SparkleSystem
            system=SparkleSystem()
        self.system=system
    def health(self):
        models=[]
        for rid,record in self.system.models._records.items():
            models.append({'record_id':rid,'provider':record.provider,'model':record.model_id,'roles':sorted(record.roles),'enabled':record.enabled,'health':self.system.models.health.status(rid)['state']})
        return {'available':True,'tools':sorted(self.system.tools.names),'models':models,'boundary':'SparkleSystem/ToolRegistry'}
    def retrieve_context(self,request,requirements):
        bundle=self.system.context.build(request)
        return {'requirements':list(requirements),'rendered':bundle.render()[:6000],'source':'gen1-context'}
    def plan(self,goal,context,available_capabilities):
        from sparkle.contracts import Message,ModelRequest
        schema={
          'goal_id':goal['goal_id'],'steps':[{'step_id':'step-1','objective':'bounded action','required_capabilities':['one exact capability'],'depends_on':[],'success_criteria':['observable result'],'arguments':{},'timeout_seconds':30,'retry_limit':1}],
          'success_criteria':[{'description':'goal result verified','verification_method':'all_steps_verified'}],
          'risk':'LOW','confidence':0.0,'unresolved_questions':[]
        }
        prompt=(
          'Create a minimal executable plan for this goal. Return ONLY one JSON object, no markdown. '
          'Use only capabilities in AVAILABLE_CAPABILITIES. Never invent tools. Each step must request exactly one capability. '
          'Dependencies must reference earlier or existing step IDs. Goal verification_method must be all_steps_verified or step_verified:<step_id>. '
          'The model proposes actions only; it cannot grant permission, approve, execute, verify, or declare completion.\n'
          f'GOAL={json.dumps({k:goal[k] for k in ("goal_id","user_request","constraints","deadline")},ensure_ascii=False)}\n'
          f'AVAILABLE_CAPABILITIES={json.dumps(available_capabilities)}\n'
          f'RELEVANT_CONTEXT={json.dumps(str(context.get("rendered",""))[:4000],ensure_ascii=False)}\n'
          f'OUTPUT_SHAPE={json.dumps(schema)}'
        )
        request=ModelRequest(messages=[Message(role='user',content=prompt)],system='You are SPARKLE Gen-2 planner. Produce strict JSON only.',max_output_tokens=2200,temperature=0.2,thinking=True,metadata={'operation':'gen2_plan','required_capabilities':['planning','reasoning']})
        decision,response=self.system.model_router.complete(request,'reasoning',modalities={'text'},latency_policy='deep',max_timeout_seconds=120)
        text=response.text.strip()
        try: raw=json.loads(text)
        except json.JSONDecodeError as exc: raise RuntimeError('planner_invalid_json') from exc
        if not isinstance(raw,dict): raise RuntimeError('planner_output_not_object')
        raw['goal_id']=goal['goal_id']
        prov={'request_id':response.provider_request_id or uuid.uuid4().hex,'provider':decision.provider,'model':decision.model,'capability':decision.capability,'requested_capabilities':['planning','reasoning'],'selection_reason':decision.selection_reason,'health':decision.health,'trace_id':None,'fallback':decision.fallback}
        return {'proposal':raw,'provenance':prov}
    def approval_status(self,approval_id,tool):
        if tool!='memory_write' or not hasattr(self.system,'memory_review'):
            return {'status':'UNKNOWN','verified':False,'reason':'unsupported_approval_type'}
        for status in ('pending','approved','rejected'):
            try: rows=self.system.memory_review.list(limit=100,status=status)
            except Exception as exc:return {'status':'UNKNOWN','verified':False,'reason':type(exc).__name__}
            for row in rows:
                if row.get('id')==approval_id:
                    state=row.get('status',status).upper();memory_id=row.get('memory_id')
                    verified=state=='APPROVED' and memory_id is not None
                    return {'status':state,'verified':verified,'memory_id':memory_id,'source':'gen1_memory_review'}
        return {'status':'UNKNOWN','verified':False,'reason':'approval_not_found'}
    def invoke(self,tool,arguments):
        if tool not in self.system.tools.names:
            return ToolObservation(False,tool,{'error':'tool unavailable'},{'verified':False,'reason':'not_registered'})
        try: output=self.system.tools.execute(tool,arguments,allowed={tool})
        except Exception as exc:
            return ToolObservation(False,tool,{'error':str(exc),'error_type':type(exc).__name__},{'verified':False,'reason':'execution_failed'})
        if not isinstance(output,dict):output={'value':output}
        if tool=='memory_write' and output.get('status')=='pending':
            pid=output.get('proposal_id'); verified=False
            if isinstance(pid,str) and hasattr(self.system,'memory_review'):
                verified=any(r.get('id')==pid for r in self.system.memory_review.list(limit=100,status='pending'))
            return ToolObservation(True,tool,output,{'verified':verified,'method':'re-read pending memory proposal'},True,pid)
        return ToolObservation(True,tool,output,{'verified':True,'method':'Gen-1 tool result contract; no model assertion'})
