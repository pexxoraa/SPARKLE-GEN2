import unittest
from sparkle_gen2.dashboard import ReadOnlyDashboard
from sparkle_gen2.daily_os import DailyOperatingSystem
from sparkle_gen2.image_runtime import ImageGenerationRuntime
from sparkle_gen2.model_manager import ModelCapabilityManager
from sparkle_gen2.retrieval import SemanticRetrievalRuntime

class G:
    def health(self):return {'models':[{'provider':'nvidia','model':'n','roles':['reasoning','coding'],'enabled':True,'health':'HEALTHY'},{'provider':'x','model':'u','roles':['reasoning'],'enabled':True,'health':'UNAVAILABLE'}]}

class Cycle8ModelUXTests(unittest.TestCase):
    def test_capability_health_filters_unavailable_models(self):
        m=ModelCapabilityManager(G());self.assertEqual(len(m.eligible('reasoning')),1);self.assertEqual(m.status('voice')['status'],'EXTERNALLY_BLOCKED')
    def test_retrieval_requires_real_embedder_and_supports_rerank(self):
        r=SemanticRetrievalRuntime();self.assertEqual(r.health()['embedding'],'EXTERNALLY_BLOCKED')
        with self.assertRaises(RuntimeError):r.retrieve('x',[{'text':'x'}])
        emb=lambda s:[float(len(s)),1.0];rr=lambda q,items:list(reversed(items))
        live=SemanticRetrievalRuntime(emb,rr);out=live.retrieve('aa',[{'text':'a','id':1},{'text':'aaaa','id':2}],2);self.assertEqual(len(out),2)
    def test_image_generation_external_block_and_injected_contract(self):
        x=ImageGenerationRuntime();self.assertEqual(x.health()['status'],'EXTERNALLY_BLOCKED')
        with self.assertRaises(RuntimeError):x.generate('cat')
        y=ImageGenerationRuntime(lambda p:{'artifact':'image://1','prompt':p});self.assertEqual(y.generate('cat')['artifact'],'image://1')
    def test_dashboard_is_read_only_renderable_snapshot(self):
        d=ReadOnlyDashboard();s=d.snapshot(capabilities=[{'name':'core'}]);h=d.render_html(s);self.assertIn('SPARKLE',h);self.assertIn('core',h)
    def test_daily_os_prioritizes_deterministically(self):
        d=DailyOperatingSystem();b=d.build_brief([{'title':'low','urgency':0,'importance':.2},{'title':'high','urgency':1,'importance':1}]);self.assertEqual(b[0]['title'],'high')

if __name__=='__main__':unittest.main()
