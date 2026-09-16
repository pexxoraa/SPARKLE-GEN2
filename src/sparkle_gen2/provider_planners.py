from __future__ import annotations
import json,socket,urllib.error,urllib.parse,urllib.request,uuid
from dataclasses import dataclass
from pathlib import Path
from .core_time import now
from .models import ModelProvenance,PlanProposal,PlanProposalStep
from .planner import PlannerError

@dataclass(slots=True)
class PlannerProviderConfig:
    provider:str; model:str; base_url:str; timeout_seconds:int=60

def _safe_base_url(value:str)->str:
    u=urllib.parse.urlparse(value.rstrip('/'))
    if u.scheme not in {'http','https'} or not u.hostname:raise ValueError('invalid_planner_base_url')
    if u.username or u.password:raise ValueError('credentials_in_planner_url_forbidden')
    if u.scheme=='http' and u.hostname not in {'127.0.0.1','localhost','::1'}:raise ValueError('plaintext_planner_must_be_loopback')
    return value.rstrip('/')

class OllamaPlannerModel:
    """Optional Ollama transport behind the provider-neutral PlannerModel contract."""
    def __init__(self,config:PlannerProviderConfig):
        if config.provider!='ollama':raise ValueError('provider_mismatch')
        self.config=config;self.base_url=_safe_base_url(config.base_url)
    def health(self):
        try:
            with urllib.request.urlopen(self.base_url+'/api/tags',timeout=min(self.config.timeout_seconds,5)) as r: data=json.loads(r.read())
            names={str(x.get('name')) for x in data.get('models',[]) if isinstance(x,dict)}
            return {'status':'HEALTHY' if self.config.model in names else 'UNAVAILABLE','provider':'ollama','model':self.config.model}
        except Exception as exc:return {'status':'UNAVAILABLE','provider':'ollama','model':self.config.model,'error_type':type(exc).__name__}
    def propose(self,goal,context,available_capabilities):
        allowed=sorted(set(str(x) for x in available_capabilities))
        schema={'steps':[{'step_id':'s1','objective':'short objective','required_capabilities':['one allowed capability'],'depends_on':[],'success_criteria':['observable criterion'],'arguments':{},'timeout_seconds':30,'retry_limit':1}], 'success_criteria':[{'description':'goal criterion','verification_method':'all_steps_verified'}], 'risk':'LOW','confidence':0.8,'unresolved_questions':[]}
        prompt=('Create a minimal executable plan as JSON only. Use ONLY required_capabilities from the supplied allowed list. '
                'Never invent tools, approvals, permissions, or completed results. Prefer one read-only step when sufficient. '
                f'Goal: {goal.user_request}\nContext: {str(context.get("rendered",""))[:4000]}\nAllowed capabilities: {json.dumps(allowed)}\nTool schemas: {json.dumps(context.get("tool_schemas",{}),ensure_ascii=False)[:12000]}\nJSON shape: {json.dumps(schema)}')
        body={'model':self.config.model,'messages':[{'role':'system','content':'You are a bounded planning model. Output valid JSON only.'},{'role':'user','content':prompt}], 'stream':False,'format':'json','think':False,'options':{'temperature':0,'num_predict':1200}}
        req=urllib.request.Request(self.base_url+'/api/chat',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=self.config.timeout_seconds) as r: response=json.loads(r.read())
        except urllib.error.HTTPError as exc:raise PlannerError(f'provider_http_{exc.code}') from exc
        except TimeoutError as exc:raise PlannerError('provider_timeout') from exc
        except Exception as exc:raise PlannerError(f'provider_error:{type(exc).__name__}') from exc
        try:
            raw=json.loads(response['message']['content'])
            steps=[PlanProposalStep(**s) for s in raw['steps']]
            proposal=PlanProposal(uuid.uuid4().hex,goal.goal_id,steps,list(raw['success_criteria']),str(raw['risk']),float(raw['confidence']),list(raw.get('unresolved_questions',[])),now())
        except Exception as exc:raise PlannerError(f'invalid_structured_output:{type(exc).__name__}') from exc
        prov=ModelProvenance(str(response.get('created_at') or uuid.uuid4().hex),'ollama',self.config.model,'reasoning',['planning','reasoning'],'configured_environment_provider','HEALTHY',fallback=False)
        return proposal,prov

def load_planner_config(path:str|Path):
    p=Path(path)
    data=json.loads(p.read_text())
    cfg=PlannerProviderConfig(str(data['provider']),str(data['model']),str(data['base_url']),max(5,min(int(data.get('timeout_seconds',60)),180)))
    adapters={'ollama':OllamaPlannerModel}
    if cfg.provider not in adapters:raise ValueError('unsupported_planner_provider')
    return adapters[cfg.provider](cfg)
