import json,tempfile,unittest,uuid
from pathlib import Path
from sparkle.registry import ModelRegistry
from sparkle.secrets import SecretResolver
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.model_manager import CapabilityRouter,ModelCapabilityManager,build_gen2_model_registry
from sparkle_gen2.models import ModelProvenance,PlanProposal,PlanProposalStep
from sparkle_gen2.storage import Gen2Store


def rec(i,roles,modalities=None,inputs=None,outputs=None,**extra):
    raw={'id':i,'provider':'nvidia','model_id':'nvidia/'+i,'adapter':'nvidia_chat_completions','roles':roles,'modalities':modalities or ['text'],'enabled':True,'supports_tools':'tool_use' in roles,'allow_fallback':False,'latency_class':'balanced','input_modalities':inputs or modalities or ['text'],'output_modalities':outputs or ['text']};raw.update(extra);return raw

def config():
    models=[
      rec('nemotron-reasoning',['general','reasoning','planning','coding','tool_use']),
      rec('nemotron-omni',['reasoning','multimodal'],['text','image','document'],['text','image','document'],['text']),
      rec('nemotron-voice',['reasoning','voice'],['text','audio'],['text','audio'],['text','audio']),
      rec('embed-slot',['embedding'],['text'],['text'],['embedding']),
      rec('rerank-slot',['reranking'],['text'],['text'],['ranking']),
      rec('image-slot',['image_generation'],['text','image'],['text'],['image']),
      rec('safety-slot',['safety'],['text'],['text'],['safety']),
    ]
    return {'active_model':'nemotron-reasoning','models':models,'routing':{'default':'nemotron-reasoning','general':'nemotron-reasoning','reasoning':'nemotron-reasoning','planning':'nemotron-reasoning','coding':'nemotron-reasoning','tool_use':'nemotron-reasoning','multimodal':'nemotron-omni','voice':'nemotron-voice','embedding':'embed-slot','reranking':'rerank-slot','image_generation':'image-slot','safety':'safety-slot'}}

def manager_from(data):
    td=tempfile.TemporaryDirectory();p=Path(td.name)/'models.json';p.write_text(json.dumps(data));registry=ModelRegistry(path=p);return td,registry,ModelCapabilityManager(registry=registry,fallback_allowed=False)

class FakeGateway:
    def health(self):return {'tools':['calculator'],'tool_definitions':[{'name':'calculator','parameters':{'type':'object'}}]}
    def retrieve_context(self,*a):return {'source':'test','rendered':''}
    def invoke(self,tool,args):return ToolObservation(True,tool,{'value':4},{'verified':True})

class AnyModelPlanner:
    def propose(self,goal,context,available):
        p=PlanProposal(uuid.uuid4().hex,goal.goal_id,[PlanProposalStep('s','calc',['calculator'],[],['verified'],{'expression':'2+2'},30,0)],[{'description':'verified','verification_method':'all_steps_verified'}],'LOW',.9,[],'test')
        return p,ModelProvenance('req-x','nvidia','nvidia/future-reasoner','reasoning',['planning','reasoning'],'capability_router_selected','AVAILABLE',fallback=False)

class Cycle51MultiModelTests(unittest.TestCase):
    def test_multiple_records_and_capability_declarations_coexist(self):
        td,registry,m=manager_from(config());self.addCleanup(td.cleanup);inventory=m.inventory();self.assertEqual(len(inventory),7);self.assertEqual({x['record_id'] for x in inventory},{x['id'] for x in config()['models']})
        bad=config();bad['models'][0]['capabilities']=['reasoning','unknown_capability'];bad['routing']={'default':'nemotron-reasoning','reasoning':'nemotron-reasoning','planning':'nemotron-reasoning','coding':'nemotron-reasoning','tool_use':'nemotron-reasoning','multimodal':'nemotron-omni','voice':'nemotron-voice','embedding':'embed-slot','reranking':'rerank-slot','image_generation':'image-slot','safety':'safety-slot'}
        td2=tempfile.TemporaryDirectory();self.addCleanup(td2.cleanup);p=Path(td2.name)/'x.json';p.write_text(json.dumps(bad));registry2=ModelRegistry(path=p)
        with self.assertRaisesRegex(ValueError,'known capabilities'):ModelCapabilityManager(registry=registry2).inventory()

    def test_reasoning_route_selects_reasoning_model_and_second_model_does_not_break_it(self):
        td,registry,m=manager_from(config());self.addCleanup(td.cleanup);r=CapabilityRouter(m).require(['reasoning','tool_use'],input_modalities=['text'],output_modalities=['text'],tools_required=True);self.assertEqual(r.selected.record_id,'nemotron-reasoning');self.assertFalse(r.fallback)

    def test_multimodal_cannot_select_text_only_model(self):
        td,registry,m=manager_from(config());self.addCleanup(td.cleanup);r=m.route(['multimodal','reasoning'],input_modalities=['text','image'],output_modalities=['text']);self.assertEqual(r.selected.record_id,'nemotron-omni');self.assertNotEqual(r.selected.record_id,'nemotron-reasoning')
        text_only=config();text_only['models']=[text_only['models'][0]];text_only['routing']={'default':'nemotron-reasoning','reasoning':'nemotron-reasoning'};td2,reg2,m2=manager_from(text_only);self.addCleanup(td2.cleanup);blocked=m2.route(['multimodal','reasoning'],input_modalities=['image'],output_modalities=['text']);self.assertIsNone(blocked.selected);self.assertEqual(blocked.status,'BLOCKED')

    def test_voice_requires_audio_capable_voice_model(self):
        td,registry,m=manager_from(config());self.addCleanup(td.cleanup);r=m.route(['voice','reasoning'],input_modalities=['audio'],output_modalities=['audio']);self.assertEqual(r.selected.record_id,'nemotron-voice');self.assertIn('audio',r.selected.input_modalities);self.assertIn('audio',r.selected.output_modalities)

    def test_embedding_reranking_image_and_safety_routes_are_distinct(self):
        td,registry,m=manager_from(config());self.addCleanup(td.cleanup)
        self.assertEqual(m.route(['embedding'],output_modalities=['embedding']).selected.record_id,'embed-slot')
        self.assertEqual(m.route(['reranking'],output_modalities=['ranking']).selected.record_id,'rerank-slot')
        self.assertEqual(m.route(['image_generation'],output_modalities=['image']).selected.record_id,'image-slot')
        self.assertEqual(m.route(['safety'],output_modalities=['safety']).selected.record_id,'safety-slot')
        for capability,output in [('embedding','embedding'),('reranking','ranking'),('image_generation','image')]:self.assertNotEqual(m.route([capability],output_modalities=[output]).selected.record_id,'nemotron-reasoning')

    def test_unavailable_model_is_explicitly_blocked_and_health_respected(self):
        data=config();embed=next(x for x in data['models'] if x['id']=='embed-slot');embed['secret_refs']=['MISSING_EMBED_KEY'];td,registry,m=manager_from(data);self.addCleanup(td.cleanup);r=m.route(['embedding'],output_modalities=['embedding']);self.assertIsNone(r.selected);self.assertEqual(r.status,'BLOCKED');row=next(x for x in m.inventory() if x['record_id']=='embed-slot');self.assertEqual(row['health'],'UNAVAILABLE');self.assertFalse(row['configured'])

    def test_fallback_false_blocks_alternate_model(self):
        class G:
            def health(self):return {'models':[{'record_id':'preferred','provider':'nvidia','model':'nvidia/a','roles':['reasoning'],'enabled':True,'configured':True,'health':'UNAVAILABLE','allow_fallback':False},{'record_id':'other','provider':'nvidia','model':'nvidia/b','roles':['reasoning'],'enabled':True,'configured':True,'health':'HEALTHY','allow_fallback':True}]}
        m=ModelCapabilityManager(G(),fallback_allowed=False);r=m.route(['reasoning'],preferred_id='preferred');self.assertIsNone(r.selected);self.assertIn('fallback disabled',r.selection_reason)

    def test_personal_agent_is_model_identity_agnostic_and_persists_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.db');result=PersonalAgent(store,FakeGateway(),planner=AnyModelPlanner()).start('calculate 2+2');self.assertEqual(result['status'],'COMPLETED');prov=result['model_provenance'];self.assertEqual(len(prov),1);self.assertEqual(prov[0]['model'],'nvidia/future-reasoner');self.assertEqual(prov[0]['capability'],'reasoning');self.assertEqual(prov[0]['selection_reason'],'capability_router_selected')

    def test_model_health_state_vocabulary_is_distinct(self):
        f=ModelCapabilityManager._health_state
        self.assertEqual(f(False,False,'UNAVAILABLE','disabled'),'BLOCKED')
        self.assertEqual(f(True,False,'UNAVAILABLE','configuration_failure'),'UNAVAILABLE')
        self.assertEqual(f(True,True,'DEGRADED','not_verified'),'AVAILABLE')
        self.assertEqual(f(True,True,'HEALTHY','verified_success'),'HEALTHY')
        self.assertEqual(f(True,True,'WARMING','startup'),'CONFIGURED')

    def test_packaged_verified_capabilities_and_remaining_optional_blocks(self):
        p=Path(__file__).parents[1]/'src/sparkle_gen2/nemotron_models.json';registry=build_gen2_model_registry(path=p,secrets=SecretResolver({'NVIDIA_API_KEY':'test-only'}));m=ModelCapabilityManager(registry=registry,fallback_allowed=False)
        self.assertEqual(m.route(['multimodal','reasoning'],input_modalities=['image'],output_modalities=['text']).selected.record_id,'nvidia-nemotron-3-nano-omni')
        self.assertEqual(m.route(['embedding'],output_modalities=['embedding']).selected.record_id,'nvidia-nemotron-3-embed-1b')
        self.assertEqual(m.status('voice')['status'],'EXTERNALLY_BLOCKED')
        self.assertEqual(m.status('image_generation')['status'],'CONNECTED' if any(registry.secrets.status(['NVIDIA_API_KEY','SPARKLE_LLM_API_KEY']).values()) else 'EXTERNALLY_BLOCKED')
        for cap in ('reranking','safety'):self.assertEqual(m.status(cap)['status'],'CONNECTED' if registry.secrets.status(['NVIDIA_API_KEY']).get('NVIDIA_API_KEY') else 'EXTERNALLY_BLOCKED')

    def test_current_packaged_nemotron_multi_model_policy_preserves_active_reasoning_and_no_fallback(self):
        p=Path(__file__).parents[1]/'src/sparkle_gen2/nemotron_models.json';data=json.loads(p.read_text());self.assertEqual(len(data['models']),7);self.assertEqual(data['active_model'],'nvidia-nemotron-3.5-lightning');self.assertTrue(all(not x['allow_fallback'] for x in data['models']));registry=build_gen2_model_registry(path=p);m=ModelCapabilityManager(registry=registry,fallback_allowed=False);rows=m.inventory();self.assertEqual({x['provider'] for x in rows},{'nvidia'});self.assertTrue(all(('nemotron' in x['model_id']) or x['model_id']=='black-forest-labs/flux.2-klein-4b' for x in rows));self.assertTrue(all(not x['fallback_eligible'] for x in rows))

if __name__=='__main__':unittest.main()
