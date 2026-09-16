import tempfile,unittest
from pathlib import Path
from sparkle_gen2.connectors import ConnectorManager,ConnectorRecord
from sparkle_gen2.devices import DeviceManager,DeviceRecord
from sparkle_gen2.diagnostics import SelfDiagnostics
from sparkle_gen2.storage import Gen2Store

class Gen1:
    def health(self):return {'available':True,'tools':['memory_search'],'agents':[{'name':'personal'}],'models':[{'record_id':'m1','provider':'nvidia','enabled':True,'health':'UNAVAILABLE'}]}
class Cycle21Tests(unittest.TestCase):
    def test_diagnosis_reports_inspected_model_connector_device_causes(self):
        with tempfile.TemporaryDirectory() as d:
            c=ConnectorManager();c.register(ConnectorRecord('gmail',['read'],'BLOCKED',external_dependency='oauth'))
            dev=DeviceManager();dev.register(DeviceRecord('robot','robot','BLOCKED',external_dependency='hardware'))
            diag=SelfDiagnostics(Gen1(),Gen2Store(Path(d)/'x.db'),c,dev);r=diag.diagnose()
            causes={(i['component'],i.get('cause')) for i in r['issues']}
            self.assertIn(('model','UNAVAILABLE'),causes);self.assertIn(('connector','oauth'),causes);self.assertIn(('device','hardware'),causes)
            self.assertTrue(r['healthy']);self.assertEqual(r['evidence']['agents'][0]['name'],'personal')
    def test_component_filter_does_not_guess(self):
        with tempfile.TemporaryDirectory() as d:
            r=SelfDiagnostics(Gen1(),Gen2Store(Path(d)/'x.db')).diagnose('missing');self.assertEqual(r['issues'],[])
if __name__=='__main__':unittest.main()
