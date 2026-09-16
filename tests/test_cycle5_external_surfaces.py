import unittest
from sparkle_gen2.devices import DeviceManager,DeviceRecord
from sparkle_gen2.multimodal import MediaInput,MultimodalGateway
from sparkle_gen2.robotics import RobotSafetyGateway
from sparkle_gen2.voice_runtime import VoiceRuntime
from sparkle_gen2.world_model import WorldModel

class Device:
    def status(self):return {'ok':True}
    def invoke(self,a,p):return {'action':a,'payload':p}

class Cycle5ExternalSurfaceTests(unittest.TestCase):
    def test_multimodal_transport_does_not_claim_semantics(self):
        g=MultimodalGateway();i=MediaInput('1','image','file://x',20)
        self.assertTrue(g.validate_transport(i));self.assertEqual(g.semantic_status(i),'EXTERNALLY_BLOCKED')
        i.semantic_verified=True;i.provider='vision-provider';self.assertEqual(g.semantic_status(i),'LIVE_VERIFIED')
    def test_voice_external_dependency_and_injected_path(self):
        v=VoiceRuntime();self.assertEqual(v.health()['stt'],'EXTERNALLY_BLOCKED')
        with self.assertRaises(RuntimeError):v.transcribe(b'x')
        live=VoiceRuntime(lambda a:'hello',lambda t:b'audio');self.assertEqual(live.transcribe(b'x'),'hello');self.assertEqual(live.speak('hi'),b'audio')
    def test_world_model_provenance_and_relationships(self):
        w=WorldModel();w.observe('p1','project',{'status':'active'},{'source':'test'});w.observe('t1','task',{'status':'open'});w.relate('p1','contains','t1')
        s=w.snapshot();self.assertEqual(s['nodes'][0]['provenance']['source'],'test');self.assertEqual(s['edges'][0]['relation'],'contains')
    def test_devices_require_approval_for_state_change(self):
        m=DeviceManager();m.register(DeviceRecord('d1','iot','CONNECTED',Device()))
        with self.assertRaises(PermissionError):m.invoke('d1','move',{})
        self.assertEqual(m.invoke('d1','move',{},approved=True)['action'],'move')
        m.register(DeviceRecord('d2','mobile','BLOCKED',external_dependency='target device'));self.assertEqual(m.health('d2')['status'],'EXTERNALLY_BLOCKED')
    def test_robot_never_allows_direct_motor_and_estop_is_independent(self):
        r=RobotSafetyGateway(lambda a,p:{'observed':a},lambda:False)
        with self.assertRaises(PermissionError):r.command('move',{},approved=False)
        with self.assertRaises(PermissionError):r.command('raw_motor',{},approved=True)
        self.assertEqual(r.command('move',{},approved=True)['observed'],'move')
        halted=RobotSafetyGateway(lambda a,p:{},lambda:True)
        with self.assertRaisesRegex(RuntimeError,'emergency_stop'):halted.command('move',{},approved=True)

if __name__=='__main__':unittest.main()
