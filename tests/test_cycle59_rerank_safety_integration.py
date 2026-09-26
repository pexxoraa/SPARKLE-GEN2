import json,math,tempfile,unittest,urllib.error
from pathlib import Path

from sparkle.model import ModelAdapter,ModelError,ModelRequest,ModelResponse
from sparkle.secrets import SecretResolver
from sparkle_gen2.model_manager import ModelCapabilityManager,build_gen2_model_registry
from sparkle_gen2.nvidia_models import NVIDIARerankingAdapter,NVIDIAContentSafetyAdapter
from sparkle_gen2.retrieval import CapabilityRoutedEmbedder,CapabilityRoutedReranker,PersistentSemanticIndex
from sparkle_gen2.safety_runtime import SafetyModelRuntime
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.models import PermissionEffect,RiskLevel

class HTTPResponse:
    def __init__(self,value):self.raw=json.dumps(value).encode()
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def read(self,n=-1):return self.raw if n<0 else self.raw[:n]

class FakeEmbed(ModelAdapter):
    provider='nvidia';model_id='nvidia/nemotron-3-embed-1b';supported_modalities=frozenset({'text'})
    def health(self):return {'configured':True}
    def complete(self,request):raise AssertionError('no chat')
    def embed(self,texts,*,input_type='query'):
        vals=[texts] if isinstance(texts,str) else list(texts)
        return [[1.0 if 'robot' in x.lower() else 0.1,1.0 if 'garden' in x.lower() else 0.1] for x in vals]

class FakeRerank(ModelAdapter):
    provider='nvidia';model_id='nvidia/llama-nemotron-rerank-vl-1b-v2';supported_modalities=frozenset({'text'});max_candidates=64
    def health(self):return {'configured':True}
    def complete(self,request):raise AssertionError('no chat')
    def rerank(self,query,passages):
        return [{'index':i,'logit':10.0 if 'robot' in p.lower() else 0.0} for i,p in sorted(enumerate(passages),key=lambda x:0 if 'robot' in x[1].lower() else 1)]

class FakeSafety(ModelAdapter):
    provider='nvidia';model_id='nvidia/nemotron-3.5-content-safety';supported_modalities=frozenset({'text'})
    def health(self):return {'configured':True}
    def complete(self,request):raise AssertionError('no chat')
    def assess(self,text):return {'label':'flagged' if 'danger' in text.lower() else 'safe','flagged':'danger' in text.lower(),'details':{'source':'fake'},'provider_request_id':'req-safe'}

class Cycle59Tests(unittest.TestCase):
    def rerank_cfg(self):return {'model_id':'nvidia/llama-nemotron-rerank-vl-1b-v2','base_url':'https://integrate.api.nvidia.com/v1/ranking','secret_refs':['NVIDIA_API_KEY'],'enabled':True,'max_candidates':4,'retry':{'attempts':1}}
    def safety_cfg(self):return {'model_id':'nvidia/nemotron-3.5-content-safety','base_url':'https://integrate.api.nvidia.com/v1/chat/completions','secret_refs':['NVIDIA_API_KEY'],'enabled':True,'retry':{'attempts':1}}

    def test_registry_records_are_nvidia_no_fallback_and_semantically_typed(self):
        data=json.loads((Path(__file__).parents[1]/'src/sparkle_gen2/nemotron_models.json').read_text());by={x['id']:x for x in data['models']}
        rr=by['nvidia-llama-nemotron-rerank-vl-1b-v2'];sf=by['nvidia-nemotron-3.5-content-safety']
        self.assertEqual((rr['provider'],rr['capabilities'],rr['output_modalities'],rr['allow_fallback']),('nvidia',['reranking'],['ranking'],False))
        self.assertEqual((sf['provider'],sf['capabilities'],sf['output_modalities'],sf['allow_fallback']),('nvidia',['safety'],['safety'],False))

    def test_exact_five_way_routing_preserves_lightning(self):
        r=build_gen2_model_registry(secrets=SecretResolver({'NVIDIA_API_KEY':'test'}));m=ModelCapabilityManager(registry=r,fallback_allowed=False)
        expected={'reasoning':'nvidia-nemotron-3.5-lightning','multimodal':'nvidia-nemotron-3-nano-omni','embedding':'nvidia-nemotron-3-embed-1b','reranking':'nvidia-llama-nemotron-rerank-vl-1b-v2','safety':'nvidia-nemotron-3.5-content-safety'}
        outputs={'reasoning':'text','multimodal':'text','embedding':'embedding','reranking':'ranking','safety':'safety'};inputs={'multimodal':['image']}
        for cap,rid in expected.items():
            route=m.route([cap],input_modalities=inputs.get(cap,['text']),output_modalities=[outputs[cap]]);self.assertEqual(route.selected.record_id,rid);self.assertFalse(route.fallback)

    def test_reranking_valid_response_and_payload(self):
        captured=[]
        def opener(req,timeout):captured.append(json.loads(req.data.decode()));return HTTPResponse({'rankings':[{'index':1,'logit':2.5},{'index':0,'logit':1.0}]})
        a=NVIDIARerankingAdapter(self.rerank_cfg(),SecretResolver({'NVIDIA_API_KEY':'secret'}),opener=opener);out=a.rerank('robot',['garden','robot']);self.assertEqual(out,[{'index':1,'logit':2.5},{'index':0,'logit':1.0}]);self.assertEqual(captured[0]['model'],'nvidia/llama-nemotron-rerank-vl-1b-v2');self.assertEqual(captured[0]['query'],{'text':'robot'});self.assertEqual(len(captured[0]['passages']),2)

    def test_reranking_rejects_malformed_indices_duplicates_missing_fields_and_nonfinite(self):
        bad=[
          {'rankings':[{'index':0,'logit':1.0}]},
          {'rankings':[{'index':2,'logit':2.0},{'index':0,'logit':1.0}]},
          {'rankings':[{'index':0,'logit':2.0},{'index':0,'logit':1.0}]},
          {'rankings':[{'index':0,'logit':2.0},{'index':1}]},
          {'rankings':[{'index':0,'logit':2.0},{'index':1,'logit':float('nan')}]},
        ]
        for value in bad:
            a=NVIDIARerankingAdapter(self.rerank_cfg(),SecretResolver({'NVIDIA_API_KEY':'x'}),opener=lambda *args,v=value,**kw:HTTPResponse(v))
            with self.subTest(value=value),self.assertRaises(ModelError):a.rerank('q',['a','b'])

    def test_reranking_missing_secret_provider_failure_and_bounds_fail_closed(self):
        a=NVIDIARerankingAdapter(self.rerank_cfg(),SecretResolver({}),opener=lambda *a,**k:HTTPResponse({}))
        with self.assertRaises(ModelError):a.rerank('q',['a'])
        def fail(*a,**k):raise urllib.error.URLError('transport')
        b=NVIDIARerankingAdapter(self.rerank_cfg(),SecretResolver({'NVIDIA_API_KEY':'x'}),opener=fail)
        with self.assertRaises(ModelError):b.rerank('q',['a'])
        with self.assertRaises(ValueError):NVIDIARerankingAdapter(self.rerank_cfg(),SecretResolver({'NVIDIA_API_KEY':'x'})).rerank('q',['x']*5)

    def test_routed_reranking_orders_semantic_candidates_and_preserves_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            r=build_gen2_model_registry(secrets=SecretResolver({'NVIDIA_API_KEY':'test'}));r.inject('nvidia-nemotron-3-embed-1b',FakeEmbed());r.inject('nvidia-llama-nemotron-rerank-vl-1b-v2',FakeRerank());m=ModelCapabilityManager(registry=r,fallback_allowed=False);store=Gen2Store(Path(d)/'g.db');idx=PersistentSemanticIndex(store,CapabilityRoutedEmbedder(m),CapabilityRoutedReranker(m));idx.upsert('garden','garden tomatoes');idx.upsert('robot','robot navigation');rows=idx.search('robot',k=2);self.assertEqual(rows[0]['id'],'robot');self.assertEqual(rows[0]['rerank_provenance']['model'],'nvidia/llama-nemotron-rerank-vl-1b-v2');self.assertFalse(rows[0]['rerank_provenance']['fallback'])

    def test_safety_adapter_parses_safe_flagged_json_and_explicit_text(self):
        cases=[({'choices':[{'message':{'content':'User Safety: safe'}}],'id':'a'},'safe',False),({'choices':[{'message':{'content':'unsafe: violence'}}],'id':'b'},'unsafe',True),({'choices':[{'message':{'content':json.dumps({'safe':False,'violations':['x']})}}],'id':'c'},'unsafe',True)]
        for payload,label,flagged in cases:
            a=NVIDIAContentSafetyAdapter(self.safety_cfg(),SecretResolver({'NVIDIA_API_KEY':'x'}),opener=lambda *args,v=payload,**kw:HTTPResponse(v));out=a.assess('text');self.assertEqual((out['label'],out['flagged']),(label,flagged));self.assertTrue(out['provider_request_id'])

    def test_safety_malformed_provider_failure_and_missing_secret_fail_closed(self):
        malformed=[{}, {'choices':[]},{'choices':[{'message':{'content':'maybe okay'}}]}]
        for value in malformed:
            a=NVIDIAContentSafetyAdapter(self.safety_cfg(),SecretResolver({'NVIDIA_API_KEY':'x'}),opener=lambda *args,v=value,**kw:HTTPResponse(v))
            with self.assertRaises(ModelError):a.assess('text')
        with self.assertRaises(ModelError):NVIDIAContentSafetyAdapter(self.safety_cfg(),SecretResolver({}),opener=lambda *a,**k:HTTPResponse({})).assess('text')
        def fail(*a,**k):raise urllib.error.URLError('transport')
        with self.assertRaises(ModelError):NVIDIAContentSafetyAdapter(self.safety_cfg(),SecretResolver({'NVIDIA_API_KEY':'x'}),opener=fail).assess('text')

    def test_advisory_safety_persists_provenance_respects_privacy_and_cannot_grant(self):
        with tempfile.TemporaryDirectory() as d:
            r=build_gen2_model_registry(secrets=SecretResolver({'NVIDIA_API_KEY':'test'}));r.inject('nvidia-nemotron-3.5-content-safety',FakeSafety());m=ModelCapabilityManager(registry=r,fallback_allowed=False);store=Gen2Store(Path(d)/'g.db');runtime=SafetyModelRuntime(model_manager=m,store=store);safe=runtime.classify('ordinary text',reference='ref-safe');flagged=runtime.classify('danger text',reference='ref-danger');self.assertEqual(safe['advisory_result']['label'],'safe');self.assertTrue(flagged['advisory_result']['flagged']);self.assertEqual(store.safety_advisories(reference='ref-danger')[0]['provider'],'nvidia');self.assertEqual(store.safety_advisories(reference='ref-danger')[0]['model'],'nvidia/nemotron-3.5-content-safety');self.assertEqual(store.safety_advisories(reference='ref-danger')[0]['provider_request_id'],'req-safe')
            with self.assertRaises(PermissionError):runtime.classify('secret content',classification='HIGHLY_SENSITIVE')
            policy=PolicyEngine();allow,_=policy.evaluate_with_advisory('document_search','user','read','now',safe);self.assertEqual(allow.effect,PermissionEffect.ALLOW);escalated,risk=policy.evaluate_with_advisory('document_search','user','read','now',flagged);self.assertEqual(escalated.effect,PermissionEffect.REQUIRE_APPROVAL);self.assertEqual(risk.level,RiskLevel.MEDIUM);denied,high=policy.evaluate_with_advisory('unknown_action','user','x','now',safe);self.assertEqual(denied.effect,PermissionEffect.DENY);denied2,high2=policy.evaluate_with_advisory('unknown_action','user','x','now',flagged);self.assertEqual(denied2.effect,PermissionEffect.DENY);self.assertEqual(high2.level,RiskLevel.HIGH)

if __name__=='__main__':unittest.main()
