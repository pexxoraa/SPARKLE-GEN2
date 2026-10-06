from __future__ import annotations
from dataclasses import asdict,dataclass
from pathlib import Path
from typing import Any
from time import monotonic


def build_gen2_model_registry(*,path:Path|None=None,secrets=None):
    from sparkle.registry import ModelRegistry
    from .nvidia_models import NVIDIAEmbeddingAdapter,NVIDIARerankingAdapter,NVIDIAContentSafetyAdapter,NVIDIAVoiceChatAdapter,NVIDIAImageGenerationAdapter
    from .gemini_voicechat_transport import GeminiLiveVoiceAdapter
    if secrets is None:
        from .protected_secrets import build_gen2_secret_resolver
        secrets=build_gen2_secret_resolver()
    registry=ModelRegistry(path=path or Path(__file__).with_name('nemotron_models.json'),secrets=secrets,adapter_factories={'nvidia_embeddings':NVIDIAEmbeddingAdapter,'nvidia_reranking':NVIDIARerankingAdapter,'nvidia_content_safety':NVIDIAContentSafetyAdapter,'nvidia_voicechat':NVIDIAVoiceChatAdapter,'gemini_voicechat':GeminiLiveVoiceAdapter,'nvidia_image_generation':NVIDIAImageGenerationAdapter})
    from .protected_secrets import protected_voice_provider
    from .voice_providers import VOICE_PROVIDER_ALIASES
    selected=protected_voice_provider()
    if selected is not None:registry.routing['voice']=VOICE_PROVIDER_ALIASES[selected]
    return registry

KNOWN_CAPABILITIES=frozenset({'general','reasoning','planning','coding','tool_use','multimodal','perception','voice','embedding','reranking','image_generation','safety'})
KNOWN_INPUT_MODALITIES=frozenset({'text','image','audio','document'})
KNOWN_OUTPUT_MODALITIES=frozenset({'text','image','audio','document','embedding','ranking','safety'})

@dataclass(frozen=True,slots=True)
class ModelRecord:
    record_id:str
    provider:str
    model_id:str
    enabled:bool
    capabilities:tuple[str,...]
    input_modalities:tuple[str,...]
    output_modalities:tuple[str,...]
    supports_tools:bool
    context_window:int|None
    max_output_tokens:int|None
    latency_class:str
    fallback_eligible:bool
    configured:bool
    health:str
    health_reason:str|None
    provenance:dict[str,Any]
    def to_dict(self):return asdict(self)

@dataclass(frozen=True,slots=True)
class CapabilityRoute:
    status:str
    required_capabilities:tuple[str,...]
    required_input_modalities:tuple[str,...]
    required_output_modalities:tuple[str,...]
    selected:ModelRecord|None
    selection_reason:str
    fallback:bool=False
    def to_dict(self):
        d=asdict(self);d['selected']=None if self.selected is None else self.selected.to_dict();return d

class ModelCapabilityManager:
    """Gen-2 typed model inventory and capability router over the existing registry conventions."""
    def __init__(self,gen1=None,*,registry=None,config_path:Path|None=None,fallback_allowed:bool=False):
        if registry is None and config_path is not None:
            registry=build_gen2_model_registry(path=config_path)
        self.gen1=gen1;self.registry=registry or getattr(getattr(gen1,'system',None),'models',None);self.fallback_allowed=bool(fallback_allowed)
        self._records_cache=None
        self._records_cache_at=0.0
        self._records_ttl=0.5
    @staticmethod
    def _validate_capabilities(values):
        if isinstance(values,str):values=[values]
        values=list(values or [])
        if not values or any(v not in KNOWN_CAPABILITIES for v in values) or len(set(values))!=len(values):raise ValueError('model capabilities must be unique known capabilities')
        return tuple(values)
    @staticmethod
    def _validate_modalities(values,field):
        values=list(values or ['text']);allowed=KNOWN_INPUT_MODALITIES if field=='input_modalities' else KNOWN_OUTPUT_MODALITIES
        if not values or any(v not in allowed for v in values) or len(set(values))!=len(values):raise ValueError(f'{field} must contain unique supported modalities')
        return tuple(values)
    @staticmethod
    def _health_state(enabled,configured,state,reason):
        if not enabled:return 'BLOCKED'
        if not configured:return 'UNAVAILABLE'
        if state=='HEALTHY':return 'HEALTHY'
        if state=='UNAVAILABLE':return 'UNAVAILABLE'
        if state in {'DEGRADED','UNKNOWN',None}:return 'AVAILABLE'
        return 'CONFIGURED'
    def _from_registry(self):
        out=[]
        for rid,raw in self.registry._records.items():
            config=raw.config;secret_refs=config.get('secret_refs',[]);secret_status=self.registry.secrets.status(secret_refs);configured=(rid in self.registry._injected_ids or not secret_refs or (all(secret_status.values()) if config.get('require_all_secret_refs') else any(secret_status.values())));configured=configured and (rid in self.registry._injected_ids or not config.get('requires_verified_transport') or bool(config.get('transport_verified',False)));hs=self.registry.health.status(rid)
            capabilities=self._validate_capabilities(config['capabilities']) if 'capabilities' in config else tuple(x for x in raw.roles if x in KNOWN_CAPABILITIES)
            inputs=self._validate_modalities(config.get('input_modalities',list(raw.modalities)),'input_modalities');outputs=self._validate_modalities(config.get('output_modalities',['text']),'output_modalities')
            out.append(ModelRecord(rid,raw.provider,raw.model_id,raw.enabled,capabilities,inputs,outputs,bool(config.get('supports_tools',False) or 'tool_use' in capabilities),config.get('context_window'),config.get('max_output_tokens'),str(config.get('latency_class','balanced')),bool(config.get('allow_fallback',False)),configured,self._health_state(raw.enabled,configured,hs.get('state'),hs.get('reason')),hs.get('reason'),{'adapter':raw.adapter,'registry_health':hs.get('state'),'health_evidence_source':hs.get('evidence_source'),'active':rid==self.registry.active_id}))
        return out
    def _from_gateway(self):
        out=[]
        for i,m in enumerate(self.gen1.health().get('models',[])):
            caps=self._validate_capabilities(m['capabilities']) if 'capabilities' in m else tuple(x for x in m.get('roles',[]) if x in KNOWN_CAPABILITIES);inputs=self._validate_modalities(m.get('input_modalities',m.get('modalities',['text'])),'input_modalities');outputs=self._validate_modalities(m.get('output_modalities',['text']),'output_modalities');configured=bool(m.get('configured',m.get('enabled',False)));state=str(m.get('health','UNAVAILABLE'))
            out.append(ModelRecord(str(m.get('record_id') or m.get('id') or f'model-{i}'),str(m.get('provider','unknown')),str(m.get('model') or m.get('model_id') or 'unknown'),bool(m.get('enabled',False)),caps,inputs,outputs,bool(m.get('supports_tools',False) or 'tool_use' in caps),m.get('context_window'),m.get('max_output_tokens'),str(m.get('latency_class','balanced')),bool(m.get('allow_fallback',False)),configured,self._health_state(bool(m.get('enabled',False)),configured,state,m.get('health_reason')),m.get('health_reason'),{'active':bool(m.get('active',False))}))
        return out
    def inventory(self):return [m.to_dict() for m in self.records()]
    def records(self):
        stamp=monotonic()
        if self._records_cache is not None and stamp-self._records_cache_at < self._records_ttl:
            return list(self._records_cache)
        records=self._from_registry() if self.registry is not None else self._from_gateway()
        self._records_cache=list(records)
        self._records_cache_at=stamp
        return list(records)
    def invalidate_records_cache(self):
        self._records_cache=None
        self._records_cache_at=0.0
    def eligible(self,capability,*,input_modalities=None,output_modalities=None,tools_required=False):
        required_caps=set(self._validate_capabilities([capability]));ins=set(self._validate_modalities(input_modalities or ['text'],'input_modalities'));outs=set(self._validate_modalities(output_modalities or ['text'],'output_modalities'))
        return [m.to_dict() for m in self.records() if m.enabled and m.configured and m.health not in {'UNAVAILABLE','BLOCKED'} and required_caps.issubset(m.capabilities) and ins.issubset(m.input_modalities) and outs.issubset(m.output_modalities) and (not tools_required or m.supports_tools)]
    def route(self,requires,*,input_modalities=None,output_modalities=None,tools_required=False,preferred_id=None):
        req=set(self._validate_capabilities(requires));ins=set(self._validate_modalities(input_modalities or ['text'],'input_modalities'));outs=set(self._validate_modalities(output_modalities or ['text'],'output_modalities'));records=self.records();candidates=[m for m in records if m.enabled and m.configured and m.health not in {'UNAVAILABLE','BLOCKED'} and req.issubset(m.capabilities) and ins.issubset(m.input_modalities) and outs.issubset(m.output_modalities) and (not tools_required or m.supports_tools)]
        if preferred_id is None and self.registry is not None:
            preferred_id=None
            for capability in sorted(req):
                routed=self.registry.routing.get(capability)
                record=next((m for m in candidates if m.record_id==routed),None)
                if record is not None:preferred_id=routed;break
            if preferred_id is None:preferred_id=self.registry.routing.get('default',self.registry.active_id)
        preferred=next((m for m in candidates if m.record_id==preferred_id),None)
        selected=preferred or (sorted(candidates,key=lambda m:(0 if m.health=='HEALTHY' else 1,m.latency_class,m.record_id))[0] if candidates else None)
        if selected is None:return CapabilityRoute('BLOCKED',tuple(sorted(req)),tuple(sorted(ins)),tuple(sorted(outs)),None,'no configured available model satisfies required capabilities/modalities',False)
        fallback=preferred_id is not None and selected.record_id!=preferred_id
        if fallback and (not self.fallback_allowed or not selected.fallback_eligible):return CapabilityRoute('BLOCKED',tuple(sorted(req)),tuple(sorted(ins)),tuple(sorted(outs)),None,'fallback disabled by product policy',False)
        return CapabilityRoute(selected.health,tuple(sorted(req)),tuple(sorted(ins)),tuple(sorted(outs)),selected,'configured capability route' if not fallback else 'approved fallback route',fallback)
    def complete(self,request,requires,*,input_modalities=None,output_modalities=None,tools_required=False,preferred_id=None):
        route=self.route(requires,input_modalities=input_modalities or getattr(request,'input_modalities',['text']),output_modalities=output_modalities or ['text'],tools_required=tools_required or bool(getattr(request,'tools',[])),preferred_id=preferred_id)
        if route.selected is None:raise RuntimeError('model_capability_unavailable:'+','.join(route.required_capabilities))
        if self.registry is None:raise RuntimeError('model_registry_execution_unavailable')
        adapter=self.registry.adapter(route.selected.record_id)
        try:response=adapter.complete(request)
        except Exception as exc:
            try:self.registry.health.failure(route.selected.record_id,exc)
            except Exception:pass
            self.invalidate_records_cache()
            raise
        try:self.registry.health.success(route.selected.record_id)
        except Exception:pass
        self.invalidate_records_cache()
        return {'route':route.to_dict(),'response':response,'provenance':{'provider':route.selected.provider,'model':route.selected.model_id,'capabilities':list(route.required_capabilities),'selection_reason':route.selection_reason,'fallback':route.fallback,'provider_request_id':getattr(response,'provider_request_id',None)}}
    def embed(self,texts,*,input_type='query'):
        route=self.route(['embedding'],input_modalities=['text'],output_modalities=['embedding'])
        if route.selected is None:raise RuntimeError('model_capability_unavailable:embedding')
        if self.registry is None:raise RuntimeError('model_registry_execution_unavailable')
        adapter=self.registry.adapter(route.selected.record_id);fn=getattr(adapter,'embed',None)
        if not callable(fn):raise RuntimeError('embedding_adapter_operation_unavailable')
        try:vectors=fn(texts,input_type=input_type)
        except Exception as exc:
            try:self.registry.health.failure(route.selected.record_id,exc)
            except Exception:pass
            self.invalidate_records_cache()
            raise
        try:self.registry.health.success(route.selected.record_id)
        except Exception:pass
        self.invalidate_records_cache()
        return {'vectors':vectors,'route':route.to_dict(),'provenance':{'provider':route.selected.provider,'model':route.selected.model_id,'capability':'embedding','input_type':input_type,'selection_reason':route.selection_reason,'fallback':route.fallback,'vector_count':len(vectors),'dimensions':len(vectors[0]) if vectors else 0}}
    def rerank(self,query,items):
        values=list(items)
        route=self.route(['reranking'],input_modalities=['text'],output_modalities=['ranking'])
        if route.selected is None:raise RuntimeError('model_capability_unavailable:reranking')
        if self.registry is None:raise RuntimeError('model_registry_execution_unavailable')
        adapter=self.registry.adapter(route.selected.record_id);fn=getattr(adapter,'rerank',None)
        if not callable(fn):raise RuntimeError('reranking_adapter_operation_unavailable')
        passages=[str(x.get('text','')) if isinstance(x,dict) else str(x) for x in values]
        try:rankings=fn(str(query),passages)
        except Exception as exc:
            try:self.registry.health.failure(route.selected.record_id,exc)
            except Exception:pass
            self.invalidate_records_cache()
            raise
        try:self.registry.health.success(route.selected.record_id)
        except Exception:pass
        self.invalidate_records_cache()
        ordered=[]
        for rank,row in enumerate(rankings,1):
            item=dict(values[row['index']]) if isinstance(values[row['index']],dict) else {'text':passages[row['index']]}
            item['rerank_score']=row['logit'];item['rerank_rank']=rank;ordered.append(item)
        return {'items':ordered,'rankings':rankings,'route':route.to_dict(),'provenance':{'provider':route.selected.provider,'model':route.selected.model_id,'capability':'reranking','selection_reason':route.selection_reason,'fallback':route.fallback,'candidate_count':len(values)}}
    def generate_image(self,prompt,*,height=1024,width=1024,samples=1,seed=1,steps=4):
        route=self.route(['image_generation'],input_modalities=['text'],output_modalities=['image'])
        if route.selected is None:raise RuntimeError('model_capability_unavailable:image_generation')
        if self.registry is None:raise RuntimeError('model_registry_execution_unavailable')
        adapter=self.registry.adapter(route.selected.record_id);fn=getattr(adapter,'generate_image',None)
        if not callable(fn):raise RuntimeError('image_generation_adapter_operation_unavailable')
        try:result=fn(prompt,height=height,width=width,samples=samples,seed=seed,steps=steps)
        except Exception as exc:
            try:self.registry.health.failure(route.selected.record_id,exc)
            except Exception:pass
            self.invalidate_records_cache()
            raise
        try:self.registry.health.success(route.selected.record_id)
        except Exception:pass
        self.invalidate_records_cache()
        return {'result':result,'route':route.to_dict(),'provenance':{'provider':route.selected.provider,'model':route.selected.model_id,'capability':'image_generation','selection_reason':route.selection_reason,'fallback':route.fallback,'provider_request_id':result.get('provider_request_id'),'provider_status':result.get('provider_status')}}

    def voice_provider(self,provider=None):
        preferred_id=None
        if self.registry is not None:
            from .voice_providers import VOICE_PROVIDER_ALIASES,normalize_voice_provider
            if provider is None:
                try:
                    from .protected_secrets import protected_voice_provider
                    provider=protected_voice_provider()
                except Exception:
                    provider=None
            alias=normalize_voice_provider(provider)
            preferred_id=VOICE_PROVIDER_ALIASES.get(alias) if alias else self.registry.routing.get('voice')
        route=self.route(['voice'],input_modalities=['audio'],output_modalities=['audio','text'],tools_required=False,preferred_id=preferred_id)
        if route.selected is None:raise RuntimeError('model_capability_unavailable:voice')
        if self.registry is None:raise RuntimeError('model_registry_execution_unavailable')
        adapter=self.registry.adapter(route.selected.record_id)
        return {'adapter':adapter,'route':route.to_dict(),'provenance':{'provider':route.selected.provider,'model':route.selected.model_id,'capability':'voice','selection_reason':route.selection_reason,'fallback':route.fallback,'voice_provider':provider or route.selected.provider}}

    def assess_safety(self,text):
        route=self.route(['safety'],input_modalities=['text'],output_modalities=['safety'])
        if route.selected is None:raise RuntimeError('model_capability_unavailable:safety')
        if self.registry is None:raise RuntimeError('model_registry_execution_unavailable')
        adapter=self.registry.adapter(route.selected.record_id);fn=getattr(adapter,'assess',None)
        if not callable(fn):raise RuntimeError('safety_adapter_operation_unavailable')
        try:assessment=fn(str(text))
        except Exception as exc:
            try:self.registry.health.failure(route.selected.record_id,exc)
            except Exception:pass
            self.invalidate_records_cache()
            raise
        try:self.registry.health.success(route.selected.record_id)
        except Exception:pass
        self.invalidate_records_cache()
        return {'assessment':assessment,'route':route.to_dict(),'provenance':{'provider':route.selected.provider,'model':route.selected.model_id,'capability':'safety','selection_reason':route.selection_reason,'fallback':route.fallback,'provider_request_id':assessment.get('provider_request_id')}}
    def status(self,capability):
        outputs={'embedding':['embedding'],'reranking':['ranking'],'image_generation':['image'],'safety':['safety'],'voice':['audio','text']}.get(capability,['text']);inputs={'voice':['audio']}.get(capability,['text'])
        if capability=='voice':
            try:routed=self.voice_provider();route=CapabilityRoute(**{k:v for k,v in routed['route'].items() if k!='selected'},selected=ModelRecord(**routed['route']['selected']))
            except Exception:route=self.route([capability],input_modalities=inputs,output_modalities=outputs,tools_required=False,preferred_id='__configured_voice_provider_unavailable__')
        else:route=self.route([capability],input_modalities=inputs,output_modalities=outputs)
        health_state=(route.selected.health if route.selected is not None else ('BLOCKED' if route.status=='BLOCKED' else 'UNAVAILABLE'));return {'capability':capability,'status':'CONNECTED' if route.selected is not None else 'EXTERNALLY_BLOCKED','health_state':health_state,'route':route.to_dict(),'candidates':self.eligible(capability,output_modalities=outputs,tools_required=False) if capability in KNOWN_CAPABILITIES else []}

class CapabilityRouter:
    """Capability-first facade; callers request semantics, never concrete model identities."""
    def __init__(self,manager:ModelCapabilityManager):self.manager=manager
    def route(self,requires,**kwargs):return self.manager.route(requires,**kwargs)
    def require(self,requires,**kwargs):
        route=self.route(requires,**kwargs)
        if route.selected is None:raise RuntimeError('model_capability_unavailable:'+','.join(route.required_capabilities))
        return route
    def complete(self,request,requires,**kwargs):return self.manager.complete(request,requires,**kwargs)
    def embed(self,texts,*,input_type='query'):return self.manager.embed(texts,input_type=input_type)
    def rerank(self,query,items):return self.manager.rerank(query,items)
    def assess_safety(self,text):return self.manager.assess_safety(text)
    def voice_provider(self):return self.manager.voice_provider()
    def generate_image(self,prompt,**kwargs):return self.manager.generate_image(prompt,**kwargs)
