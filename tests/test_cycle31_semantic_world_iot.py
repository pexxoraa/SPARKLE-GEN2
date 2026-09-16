import tempfile,unittest
from pathlib import Path
from sparkle_gen2.context_sources import PersonalContextAssembler
from sparkle_gen2.devices import DeviceManager,DeviceRecord
from sparkle_gen2.retrieval import PersistentSemanticIndex
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.world_model import WorldModel

def embed(t):
    t=t.lower();return [1.0 if 'alpha' in t else 0.0,1.0 if 'beta' in t else 0.0]
class D:
    def status(self):return {'ok':True}
    def invoke(self,a,p):return {'action':a}
    def verify(self,a,r):return {'verified':True}

class Cycle31Tests(unittest.TestCase):
    def test_persistent_vector_index_feeds_bounded_context(self):
        with tempfile.TemporaryDirectory() as d:
            s=Gen2Store(Path(d)/'x.db');idx=PersistentSemanticIndex(s,embed);idx.upsert('a','alpha project document',metadata={'project':'p'});idx.upsert('b','beta note')
            recovered=PersistentSemanticIndex(Gen2Store(Path(d)/'x.db'),embed);self.assertEqual(recovered.search('alpha',k=1)[0]['id'],'a');ctx=PersonalContextAssembler(store=s,semantic_index=recovered).gather('alpha');self.assertEqual(ctx['items'][0]['source'],'semantic')
    def test_world_model_rejects_untyped_entities_and_relationships(self):
        w=WorldModel();w.observe('p','project',{});w.observe('t','task',{});w.relate('p','contains','t')
        with self.assertRaises(ValueError):w.observe('x','mystery',{})
        with self.assertRaises(ValueError):w.relate('p','mystery_relation','t')
    def test_device_denies_arbitrary_gpio_and_undeclared_capability(self):
        m=DeviceManager();m.register(DeviceRecord('esp','device','CONNECTED',D(),capabilities=['set_relay']))
        with self.assertRaisesRegex(PermissionError,'gpio'):m.invoke('esp','raw_gpio',{},approved=True)
        with self.assertRaisesRegex(PermissionError,'not_declared'):m.invoke('esp','move',{},approved=True)
        self.assertEqual(m.invoke('esp','set_relay',{},approved=True)['action'],'set_relay');self.assertEqual(m.discover()[0]['type'],'device')
if __name__=='__main__':unittest.main()
