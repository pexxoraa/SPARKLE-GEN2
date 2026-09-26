import base64,hashlib,json,struct,tempfile,unittest,urllib.error,uuid,zlib
from pathlib import Path
from types import SimpleNamespace

from sparkle.artifacts import ArtifactManager
from sparkle.model import ModelAdapter,ModelError
from sparkle.secrets import SecretResolver
from sparkle.system import SparkleSystem
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.gen1 import LocalGen1Gateway
from sparkle_gen2.image_runtime import ImageGenerationService,inspect_image_bytes
from sparkle_gen2.model_manager import ModelCapabilityManager,build_gen2_model_registry
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.nvidia_models import NVIDIAImageGenerationAdapter
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.core_time import now


def png(width=1024,height=1024):
    raw=b''.join(b'\x00'+b'\x20\x80\xc0'*width for _ in range(height))
    def c(t,d):return struct.pack('>I',len(d))+t+d+struct.pack('>I',zlib.crc32(t+d)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+c(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+c(b'IDAT',zlib.compress(raw))+c(b'IEND',b'')

def jpeg_container(width=1024,height=1024):
    # Use a real encoded JPEG so integrity tests cover decoding, not header acceptance.
    import io
    from PIL import Image
    output=io.BytesIO()
    with Image.new('RGB',(width,height),(32,128,192)) as picture:picture.save(output,format='JPEG')
    return output.getvalue()

class HTTPResponse:
    def __init__(self,value,headers=None,raw=False):self.raw=value if raw else json.dumps(value).encode();self.headers=headers or {}
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def read(self,n=-1):return self.raw if n<0 else self.raw[:n]

class FakeImageAdapter(ModelAdapter):
    provider='nvidia';model_id='black-forest-labs/flux.2-klein-4b';supported_modalities=frozenset({'text'})
    def __init__(self,image=None):self.image=image or png();self.calls=0
    def health(self):return {'configured':True}
    def complete(self,request):raise AssertionError('image generation must not use chat completion')
    def generate_image(self,prompt,**kwargs):self.calls+=1;return {'image_bytes':self.image,'seed':kwargs['seed'],'finish_reason':'SUCCESS','provider_request_id':'nvcf-test','provider_status':'fulfilled'}

class ArtifactGateway(LocalGen1Gateway):
    def __init__(self,root):
        super().__init__(SparkleSystem());manager=ArtifactManager(workspace_root=root/'workspaces',artifact_root=root/'artifacts',path=root/'artifacts.db');manager.initialize();self.system.artifacts=manager

class Cycle62Tests(unittest.TestCase):
    def cfg(self):return {'model_id':'black-forest-labs/flux.2-klein-4b','base_url':'https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.2-klein-4b','secret_refs':['NVIDIA_API_KEY'],'enabled':True,'retry':{'attempts':1}}
    def manager(self,adapter=None):
        p=Path(__file__).parents[1]/'src/sparkle_gen2/nemotron_models.json';r=build_gen2_model_registry(path=p,secrets=SecretResolver({'NVIDIA_API_KEY':'test-only'}));
        if adapter is not None:r.inject('nvidia-flux-2-klein-4b',adapter)
        return ModelCapabilityManager(registry=r,fallback_allowed=False)
    def service(self,d,adapter=None):
        root=Path(d);store=Gen2Store(root/'g2.db');gateway=ArtifactGateway(root);a=adapter or FakeImageAdapter();m=self.manager(a);return store,gateway,a,ImageGenerationService(store,m,gateway)

    def test_registry_record_is_exact_nvidia_flux_image_route_no_fallback(self):
        d=json.loads((Path(__file__).parents[1]/'src/sparkle_gen2/nemotron_models.json').read_text());m=next(x for x in d['models'] if x['id']=='nvidia-flux-2-klein-4b');self.assertEqual(m['provider'],'nvidia');self.assertEqual(m['model_id'],'black-forest-labs/flux.2-klein-4b');self.assertEqual(m['capabilities'],['image_generation']);self.assertEqual(m['input_modalities'],['text']);self.assertEqual(m['output_modalities'],['image']);self.assertFalse(m['allow_fallback']);self.assertEqual(d['routing']['image_generation'],'nvidia-flux-2-klein-4b');self.assertNotIn('cfg_scale',m);self.assertNotIn('mode',m)

    def test_six_way_routing_is_exact_and_image_does_not_hijack_reasoning(self):
        m=self.manager();expected={'reasoning':'nvidia-nemotron-3.5-lightning','multimodal':'nvidia-nemotron-3-nano-omni','embedding':'nvidia-nemotron-3-embed-1b','reranking':'nvidia-llama-nemotron-rerank-vl-1b-v2','image_generation':'nvidia-flux-2-klein-4b','safety':'nvidia-nemotron-3.5-content-safety'};io={'reasoning':(['text'],['text']),'multimodal':(['image'],['text']),'embedding':(['text'],['embedding']),'reranking':(['text'],['ranking']),'image_generation':(['text'],['image']),'safety':(['text'],['safety'])}
        for cap,rid in expected.items():q=m.route([cap],input_modalities=io[cap][0],output_modalities=io[cap][1]);self.assertEqual(q.selected.record_id,rid);self.assertFalse(q.fallback)
        self.assertNotEqual(m.route(['image_generation'],input_modalities=['text'],output_modalities=['image']).selected.record_id,'nvidia-nemotron-3.5-lightning')

    def test_adapter_sends_only_verified_contract_and_decodes_artifact(self):
        captured=[];image=png()
        def opener(req,timeout):captured.append(json.loads(req.data.decode()));return HTTPResponse({'artifacts':[{'base64':base64.b64encode(image).decode(),'finishReason':'SUCCESS','seed':1}]},{'Nvcf-Status':'fulfilled','Nvcf-Reqid':'req-1'})
        a=NVIDIAImageGenerationAdapter(self.cfg(),SecretResolver({'NVIDIA_API_KEY':'secret'}),opener=opener);out=a.generate_image('a blue square',height=1024,width=1024,samples=1,seed=1,steps=4);self.assertEqual(out['image_bytes'],image);self.assertEqual(out['provider_status'],'fulfilled');self.assertEqual(out['provider_request_id'],'req-1');self.assertEqual(captured[0],{'prompt':'a blue square','height':1024,'width':1024,'samples':1,'seed':1,'steps':4});self.assertNotIn('cfg_scale',captured[0]);self.assertNotIn('mode',captured[0]);self.assertNotIn('secret',json.dumps(captured[0]))

    def test_request_validation_fails_closed(self):
        a=NVIDIAImageGenerationAdapter(self.cfg(),SecretResolver({'NVIDIA_API_KEY':'x'}),opener=lambda *a,**k:HTTPResponse({}))
        bad=[('',{}),('x',{'height':255}),('x',{'width':2056}),('x',{'height':1001}),('x',{'samples':2}),('x',{'steps':0}),('x',{'steps':51}),('x',{'seed':-1}),('x',{'seed':4294967296}),('x'*16001,{})]
        for prompt,kw in bad:
            args={'height':1024,'width':1024,'samples':1,'seed':1,'steps':4}|kw
            with self.subTest(prompt_len=len(prompt),kw=kw),self.assertRaises(ValueError):a.generate_image(prompt,**args)

    def test_response_validation_missing_malformed_invalid_and_metadata(self):
        image=png();bad=[{}, {'artifacts':[]},{'artifacts':[{},{}]},{'artifacts':[{}]},{'artifacts':[{'base64':'***','seed':1}]},{'artifacts':[{'base64':base64.b64encode(b'not-image').decode(),'seed':1}]},{'artifacts':[{'base64':base64.b64encode(image).decode(),'seed':float('nan')}]},{'artifacts':[{'base64':base64.b64encode(image).decode(),'seed':1,'finishReason':3}]}]
        for value in bad:
            a=NVIDIAImageGenerationAdapter(self.cfg(),SecretResolver({'NVIDIA_API_KEY':'x'}),opener=lambda *args,v=value,**kw:HTTPResponse(v))
            with self.subTest(value=str(value)[:80]),self.assertRaises(ModelError):a.generate_image('x')
        a=NVIDIAImageGenerationAdapter(self.cfg(),SecretResolver({'NVIDIA_API_KEY':'x'}),opener=lambda *a,**k:HTTPResponse({'artifacts':[{'base64':base64.b64encode(b'x'*17).decode(),'seed':1}]}));a.MAX_DECODED_BYTES=16
        with self.assertRaises(ModelError):a.generate_image('x')

    def test_provider_http_timeout_missing_secret_and_malformed_json_fail_without_fallback(self):
        def http(*a,**k):raise urllib.error.URLError('provider transport failure')
        for opener in (http,lambda *a,**k:(_ for _ in ()).throw(TimeoutError('slow')),lambda *a,**k:HTTPResponse(b'{bad',raw=True)):
            a=NVIDIAImageGenerationAdapter(self.cfg(),SecretResolver({'NVIDIA_API_KEY':'x'}),opener=opener)
            with self.assertRaises(ModelError):a.generate_image('x')
        with self.assertRaises(ModelError):NVIDIAImageGenerationAdapter(self.cfg(),SecretResolver({}),opener=lambda *a,**k:HTTPResponse({})).generate_image('x')

    def test_independent_png_and_jpeg_container_validation(self):
        p=inspect_image_bytes(png(32,24));self.assertEqual((p.media_type,p.width,p.height),('image/png',32,24));j=inspect_image_bytes(jpeg_container(40,30));self.assertEqual((j.media_type,j.width,j.height),('image/jpeg',40,30))
        for raw in (b'',b'not-image',b'\xff\xd8'+b'x'*100+b'\xff\xd9',b'\x89PNG\r\n\x1a\n'+b'x'*40):
            with self.assertRaises(ValueError):inspect_image_bytes(raw)

    def test_generated_image_persists_in_authoritative_artifact_registry_and_rereads_digest(self):
        with tempfile.TemporaryDirectory() as d:
            store,g,a,svc=self.service(d);r=svc.generate({'prompt':'a blue square','height':1024,'width':1024,'seed':1,'steps':4},user_id='u',goal_id='g',task_run_id='t',trace_id='tr',step_id='s');self.assertEqual(r.status,'VERIFIED');self.assertTrue(r.verification['verified']);self.assertEqual(r.media_type,'image/png');self.assertEqual((r.width,r.height),(1024,1024));content=g.artifact_content(r.artifact_id);self.assertEqual(content['sha256'],r.artifact_sha256);row=next(x for x in g.artifacts(100) if x['artifact_id']==r.artifact_id);manifest=row['manifest'];self.assertEqual(manifest['model'],'black-forest-labs/flux.2-klein-4b');self.assertEqual(manifest['provider'],'nvidia');self.assertEqual(manifest['capability'],'image_generation');self.assertFalse(manifest['fallback']);self.assertEqual(manifest['request_id'],r.request_id);self.assertEqual(manifest['media_type'],'image/png');self.assertNotIn('NVIDIA_API_KEY',json.dumps(manifest));self.assertNotIn('Authorization',json.dumps(manifest));self.assertNotIn('a blue square',json.dumps(manifest))

    def test_idempotent_retry_reuses_verified_artifact_without_second_provider_call(self):
        with tempfile.TemporaryDirectory() as d:
            store,g,a,svc=self.service(d);ctx=dict(user_id='u',goal_id='g',task_run_id='t',trace_id='tr',step_id='s');one=svc.generate({'prompt':'same prompt'},**ctx);two=svc.generate({'prompt':'same prompt'},**ctx);self.assertEqual(one.request_id,two.request_id);self.assertEqual(one.artifact_id,two.artifact_id);self.assertTrue(two.reused);self.assertEqual(a.calls,1);self.assertEqual(len(g.artifacts(100)),1)

    def test_failed_provider_persists_failed_request_and_no_artifact(self):
        class F(FakeImageAdapter):
            def generate_image(self,*a,**k):self.calls+=1;raise RuntimeError('provider unavailable')
        with tempfile.TemporaryDirectory() as d:
            store,g,a,svc=self.service(d,F())
            with self.assertRaises(RuntimeError):svc.generate({'prompt':'x'},user_id='u',goal_id='g',task_run_id='t',trace_id='tr',step_id='s')
            state=store.image_generation_requests(owner_user_id='u')[0];self.assertEqual(state['status'],'FAILED');self.assertIsNone(state['artifact_id']);self.assertEqual(g.artifacts(100),[])

    def test_sensitive_classification_blocks_before_provider_and_does_not_persist_prompt(self):
        with tempfile.TemporaryDirectory() as d:
            store,g,a,svc=self.service(d)
            for c in ('SENSITIVE','HIGHLY_SENSITIVE','DEVICE_CONTROL'):
                with self.subTest(c=c),self.assertRaises(PermissionError):svc.generate({'prompt':'protected secret prompt','classification':c},user_id='u',goal_id='g'+c,task_run_id='t',trace_id='tr',step_id='s')
            self.assertEqual(a.calls,0);self.assertEqual(g.artifacts(100),[]);self.assertNotIn('protected secret prompt',json.dumps(store.image_generation_requests(owner_user_id='u')))

    def test_personalagent_requires_exact_human_approval_then_persists_verified_artifact(self):
        with tempfile.TemporaryDirectory() as d:
            store,g,a,svc=self.service(d);plan=PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('img','Generate approved image',['image_generate'],[],['artifact reread verified'],{'prompt':'a blue square','height':1024,'width':1024,'samples':1,'seed':1,'steps':4,'classification':'PRIVATE'},30,0)],[{'description':'image verified','verification_method':'all_steps_verified'}],'MEDIUM',.99,[],now());agent=PersonalAgent(store,g,planner=StaticPlanner(plan),image_service=svc);first=agent.start('Generate an image.',user_id='u');self.assertEqual(first['status'],'WAITING');self.assertEqual(a.calls,0);self.assertEqual(g.artifacts(100),[]);agent.decide_approval(first['approvals'][0],'approve',actor='human-reviewer');done=agent.resume(first['goal_id']);self.assertEqual(done['status'],'COMPLETED');self.assertEqual(a.calls,1);run=store.load_task_run_for_goal(first['goal_id']);self.assertEqual(len(run.artifacts),1);self.assertIn('Generated and independently verified',done['text'])

    def test_model_supplied_approval_and_scope_mutation_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            store,g,a,svc=self.service(d);plan=PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('img','Generate image',['image_generate'],[],['verified'],{'prompt':'A','approved':True},30,0)],[{'description':'v','verification_method':'all_steps_verified'}],'MEDIUM',.9,[],now());agent=PersonalAgent(store,g,planner=StaticPlanner(plan),image_service=svc);r=agent.start('x');self.assertEqual(r['status'],'BLOCKED');self.assertEqual(a.calls,0)
        with tempfile.TemporaryDirectory() as d:
            store,g,a,svc=self.service(d);plan=PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('img','Generate image',['image_generate'],[],['verified'],{'prompt':'A'},30,0)],[{'description':'v','verification_method':'all_steps_verified'}],'MEDIUM',.9,[],now());agent=PersonalAgent(store,g,planner=StaticPlanner(plan),image_service=svc);r=agent.start('x');agent.decide_approval(r['approvals'][0],'approve',actor='human');saved=store.load_plan(store.load_goal(r['goal_id']).plan_id);saved.steps[0].arguments['prompt']='B';store.save_plan(saved);out=agent.resume(r['goal_id']);self.assertEqual(out['status'],'BLOCKED');self.assertEqual(a.calls,0)

if __name__=='__main__':unittest.main()
