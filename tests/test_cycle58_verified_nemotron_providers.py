import io,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace

from sparkle.model import ModelAdapter,ModelError,ModelRequest,ModelResponse
from sparkle.contracts import Message
from sparkle.content import ContentEnvelope,ContentPart
from sparkle.secrets import SecretResolver
from sparkle_gen2.model_manager import CapabilityRouter,ModelCapabilityManager,build_gen2_model_registry
from sparkle_gen2.nvidia_models import NVIDIAEmbeddingAdapter
from sparkle_gen2.retrieval import CapabilityRoutedEmbedder,SemanticRetrievalRuntime,PersistentSemanticIndex
from sparkle_gen2.document_intelligence import DocumentIntelligenceService
from sparkle_gen2.context_sources import PersonalContextAssembler
from sparkle_gen2.storage import Gen2Store

class HTTPResponse:
    def __init__(self,value):self.raw=json.dumps(value).encode()
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def read(self):return self.raw

class FakeEmbed(ModelAdapter):
    provider='nvidia';model_id='nvidia/nemotron-3-embed-1b';supported_modalities=frozenset({'text'})
    def health(self):return {'configured':True}
    def complete(self,request):raise AssertionError('chat completion must not be used for embedding route')
    def embed(self,texts,*,input_type='query'):
        def v(t):
            low=t.lower();return [1.0 if 'robot' in low else 0.0,1.0 if 'garden' in low else 0.0,1.0 if input_type=='query' else .9]
        return [v(t) for t in ([texts] if isinstance(texts,str) else texts)]

class FakeOmni(ModelAdapter):
    provider='nvidia';model_id='nvidia/nemotron-3-nano-omni-30b-a3b-reasoning';supported_modalities=frozenset({'text','image'})
    def health(self):return {'configured':True}
    def complete(self,request):
        self.validate_request(request);return ModelResponse('red square',self.model_id,self.provider,'stop',provider_request_id='omni-test')

class Cycle58Tests(unittest.TestCase):
    def test_packaged_routes_verified_nemotron_capabilities_without_fallback(self):
        p=Path(__file__).parents[1]/'src/sparkle_gen2/nemotron_models.json';r=build_gen2_model_registry(path=p,secrets=SecretResolver({'NVIDIA_API_KEY':'test-only'}));m=ModelCapabilityManager(registry=r,fallback_allowed=False)
        reasoning=m.route(['planning','reasoning'],input_modalities=['text'],output_modalities=['text']);omni=m.route(['multimodal','reasoning'],input_modalities=['image'],output_modalities=['text']);embed=m.route(['embedding'],input_modalities=['text'],output_modalities=['embedding'])
        self.assertEqual(reasoning.selected.record_id,'nvidia-nemotron-3.5-lightning');self.assertEqual(omni.selected.record_id,'nvidia-nemotron-3-nano-omni');self.assertEqual(embed.selected.record_id,'nvidia-nemotron-3-embed-1b');self.assertFalse(reasoning.fallback or omni.fallback or embed.fallback)

    def test_text_only_reasoner_cannot_satisfy_image_route(self):
        p=Path(__file__).parents[1]/'src/sparkle_gen2/nemotron_models.json';r=build_gen2_model_registry(path=p,secrets=SecretResolver({'NVIDIA_API_KEY':'test-only'}));m=ModelCapabilityManager(registry=r,fallback_allowed=False);route=m.route(['multimodal','reasoning'],input_modalities=['image'],output_modalities=['text']);self.assertNotEqual(route.selected.record_id,'nvidia-nemotron-3.5-lightning');self.assertIn('image',route.selected.input_modalities)

    def test_embedding_adapter_uses_bounded_embeddings_contract(self):
        captured=[]
        def opener(req,timeout):
            captured.append((json.loads(req.data.decode()),dict(req.header_items()),timeout));return HTTPResponse({'data':[{'index':0,'embedding':[.1,.2,.3]},{'index':1,'embedding':[.4,.5,.6]}]})
        cfg={'model_id':'nvidia/nemotron-3-embed-1b','base_url':'https://integrate.api.nvidia.com/v1/embeddings','secret_refs':['NVIDIA_API_KEY'],'enabled':True,'retry':{'attempts':1}}
        a=NVIDIAEmbeddingAdapter(cfg,SecretResolver({'NVIDIA_API_KEY':'test-secret'}),opener=opener);vectors=a.embed(['alpha','beta'],input_type='passage');self.assertEqual(vectors,[[.1,.2,.3],[.4,.5,.6]]);self.assertEqual(captured[0][0],{'input':['alpha','beta'],'model':'nvidia/nemotron-3-embed-1b','input_type':'passage'});self.assertNotIn('test-secret',json.dumps(captured[0][0]));self.assertEqual(a.health()['operation'],'embeddings')

    def test_embedding_adapter_rejects_invalid_input_and_malformed_response(self):
        cfg={'model_id':'nvidia/nemotron-3-embed-1b','base_url':'https://integrate.api.nvidia.com/v1/embeddings','secret_refs':['NVIDIA_API_KEY'],'enabled':True,'retry':{'attempts':1}}
        a=NVIDIAEmbeddingAdapter(cfg,SecretResolver({'NVIDIA_API_KEY':'x'}),opener=lambda *a,**k:HTTPResponse({'data':[{'index':0,'embedding':[]}] }));
        with self.assertRaises(ValueError):a.embed('',input_type='query')
        with self.assertRaises(ValueError):a.embed('x',input_type='other')
        with self.assertRaises(ModelError):a.embed('x')

    def test_capability_routed_embedding_drives_semantic_retrieval(self):
        p=Path(__file__).parents[1]/'src/sparkle_gen2/nemotron_models.json';r=build_gen2_model_registry(path=p,secrets=SecretResolver({'NVIDIA_API_KEY':'test-only'}));r.inject('nvidia-nemotron-3-embed-1b',FakeEmbed());m=ModelCapabilityManager(registry=r,fallback_allowed=False);embedder=CapabilityRoutedEmbedder(m);runtime=SemanticRetrievalRuntime(embedder=embedder);docs=[{'id':'garden','text':'garden soil flowers'},{'id':'robot','text':'robot localization navigation'}];result=runtime.retrieve('robot navigation',docs,k=1);self.assertEqual(result[0]['id'],'robot');self.assertEqual(embedder.health()['embedding'],'CONNECTED')

    def test_multimodal_complete_uses_capability_route_and_image_envelope(self):
        p=Path(__file__).parents[1]/'src/sparkle_gen2/nemotron_models.json';r=build_gen2_model_registry(path=p,secrets=SecretResolver({'NVIDIA_API_KEY':'test-only'}));r.inject('nvidia-nemotron-3-nano-omni',FakeOmni());m=ModelCapabilityManager(registry=r,fallback_allowed=False);env=ContentEnvelope([ContentPart.text('Describe this image.'),ContentPart.binary('image',b'fake-image-bytes',media_type='image/png')]);req=ModelRequest(messages=[Message(role='user',content=env)],thinking=False,max_output_tokens=32);out=m.complete(req,['multimodal','reasoning'],input_modalities=['text','image'],output_modalities=['text']);self.assertEqual(out['route']['selected']['record_id'],'nvidia-nemotron-3-nano-omni');self.assertEqual(out['response'].text,'red square');self.assertFalse(out['provenance']['fallback'])

    def test_document_image_understanding_uses_omni_and_preserves_privacy_boundary(self):
        import struct,zlib
        def png():
            w=h=8;raw=b''.join(b'\x00'+b'\xff\x00\x00'*w for _ in range(h))
            def c(t,d):return struct.pack('>I',len(d))+t+d+struct.pack('>I',zlib.crc32(t+d)&0xffffffff)
            return b'\x89PNG\r\n\x1a\n'+c(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+c(b'IDAT',zlib.compress(raw))+c(b'IEND',b'')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);img=root/'red.png';img.write_bytes(png());r=build_gen2_model_registry(path=Path(__file__).parents[1]/'src/sparkle_gen2/nemotron_models.json',secrets=SecretResolver({'NVIDIA_API_KEY':'test-only'}));r.inject('nvidia-nemotron-3-nano-omni',FakeOmni());m=ModelCapabilityManager(registry=r,fallback_allowed=False);store=Gen2Store(root/'g.db');svc=DocumentIntelligenceService(store,allowed_roots=[root],model_manager=m);record=svc.ingest_path(img,user_id='u',classification='PRIVATE');self.assertEqual(record.status,'READY');self.assertEqual(record.structured_content['type'],'image');self.assertIn('red square',record.structured_content['description']);self.assertEqual(record.provenance['model']['model'],'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning');self.assertFalse(record.provenance['local_only_extraction']);blocked=svc.ingest_path(img,user_id='s',classification='HIGHLY_SENSITIVE');self.assertEqual(blocked.status,'BLOCKED');self.assertEqual(blocked.failure['category'],'EXTERNALLY_BLOCKED')

    def test_persistent_semantic_index_flows_into_personal_context_via_capability_router(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(__file__).parents[1]/'src/sparkle_gen2/nemotron_models.json';r=build_gen2_model_registry(path=p,secrets=SecretResolver({'NVIDIA_API_KEY':'test-only'}));r.inject('nvidia-nemotron-3-embed-1b',FakeEmbed());m=ModelCapabilityManager(registry=r,fallback_allowed=False);store=Gen2Store(Path(d)/'g.db');idx=PersistentSemanticIndex(store,CapabilityRoutedEmbedder(m));idx.upsert('robot-doc','robot localization navigation odometry',metadata={'project':'robotics'});idx.upsert('garden-doc','garden soil tomatoes',metadata={'project':'garden'});ctx=PersonalContextAssembler(store=store,semantic_index=idx).gather('robot navigation');semantic=[x for x in ctx['items'] if x['source']=='semantic'];self.assertTrue(semantic);self.assertEqual(semantic[0]['key'],'robot-doc');self.assertEqual(semantic[0]['provenance']['metadata']['project'],'robotics')

    def test_missing_secret_fails_closed_instead_of_using_other_model(self):
        p=Path(__file__).parents[1]/'src/sparkle_gen2/nemotron_models.json';r=build_gen2_model_registry(path=p,secrets=SecretResolver({}));m=ModelCapabilityManager(registry=r,fallback_allowed=False);self.assertIsNone(m.route(['embedding'],output_modalities=['embedding']).selected);self.assertIsNone(m.route(['multimodal'],input_modalities=['image'],output_modalities=['text']).selected)

if __name__=='__main__':unittest.main()
