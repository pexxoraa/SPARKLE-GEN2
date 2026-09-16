import unittest
from sparkle_gen2.connectors import ConnectorManager,ConnectorRecord
from sparkle_gen2.diagnostics import SelfDiagnostics
from sparkle_gen2.observability import TraceRecorder
from sparkle_gen2.tool_system import CapabilityCatalog,CapabilityDescriptor

class FakeConnector:
    def health(self):return {'ok':True}
    def invoke(self,operation,payload):return {'operation':operation,'payload':payload}
class FakeGen1:
    def health(self):return {'available':True,'tools':['skill_search']}

class Cycle4PlatformTests(unittest.TestCase):
    def test_capability_catalog_is_typed_and_rejects_bad_risk(self):
        c=CapabilityCatalog();d=CapabilityDescriptor('gmail.read','1','gmail.read',{'type':'object'},{'type':'object'},'oauth','user','LOW',30,'safe','provider reread',None)
        c.register(d);self.assertEqual(c.get('gmail.read').capability,'gmail.read')
        with self.assertRaises(ValueError):c.register(CapabilityDescriptor('bad','1','bad',{}, {},'none','none','INVALID',30,'none','none',None))
    def test_connector_scope_enforcement_and_external_block(self):
        m=ConnectorManager();m.register(ConnectorRecord('gmail',['gmail.read'],'BLOCKED',external_dependency='oauth credentials'))
        self.assertEqual(m.health('gmail')['status'],'EXTERNALLY_BLOCKED')
        with self.assertRaises(PermissionError):m.invoke('gmail','send',{},'gmail.send')
        m2=ConnectorManager();m2.register(ConnectorRecord('files',['files.read'],'CONNECTED',FakeConnector()))
        self.assertTrue(m2.invoke('files','read',{'path':'x'},'files.read')['result']['payload'])
    def test_self_diagnosis_reports_actual_health(self):
        m=ConnectorManager();m.register(ConnectorRecord('calendar',['calendar.read'],'BLOCKED',external_dependency='oauth'))
        r=SelfDiagnostics(FakeGen1(),object(),m).inspect();self.assertTrue(r['healthy']);self.assertEqual(r['connectors'][0]['status'],'EXTERNALLY_BLOCKED')
    def test_trace_correlation(self):
        tr=TraceRecorder();t=tr.record('tool','skill_search','OK',goal_id='g1',task_run_id='t1',correlation={'provider':'nvidia'})
        self.assertEqual(tr.list('g1')[0].trace_id,t.trace_id);self.assertEqual(tr.list('g1')[0].correlation['provider'],'nvidia')

if __name__=='__main__':unittest.main()
