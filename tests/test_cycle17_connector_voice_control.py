import unittest
from sparkle_gen2.connectors import ConnectorManager,ConnectorRecord
from sparkle_gen2.voice_runtime import VoiceRuntime

class Adapter:
    def health(self):return {'ok':True}
    def invoke(self,operation,payload):return {'operation':operation,'payload':payload}
    def verify(self,operation,result):return {'verified':result.get('operation')==operation,'method':'provider_reread'}

class Cycle17Tests(unittest.TestCase):
    def test_connector_authorize_connect_invoke_verify_revoke(self):
        m=ConnectorManager();m.register(ConnectorRecord('mail',['read','send'],'BLOCKED',external_dependency='oauth'))
        with self.assertRaises(PermissionError):m.connect('mail',Adapter())
        m.authorize('mail',['read']);m.connect('mail',Adapter())
        self.assertEqual(m.health('mail')['status'],'CONNECTED')
        with self.assertRaises(PermissionError):m.invoke('mail','send',{},'send')
        result=m.invoke('mail','read',{},'read');self.assertTrue(m.verify('mail','read',result['result'])['verified'])
        m.revoke('mail');self.assertEqual(m.health('mail')['status'],'REVOKED');self.assertEqual(m.health('mail')['granted_scopes'],[])
    def test_connector_cannot_authorize_undeclared_scope(self):
        m=ConnectorManager();m.register(ConnectorRecord('drive',['read'],'BLOCKED'))
        with self.assertRaises(PermissionError):m.authorize('drive',['write'])
    def test_voice_turn_can_be_interrupted_before_playback(self):
        holder={}
        def tts(text):holder['v'].interrupt(holder['turn']);return b'audio'
        v=VoiceRuntime(lambda b:'hello',tts);holder['v']=v;turn=v.begin_turn();holder['turn']=turn
        with self.assertRaisesRegex(RuntimeError,'voice_interrupted'):v.speak('response',turn_id=turn)
        self.assertTrue(v.is_interrupted(turn))
if __name__=='__main__':unittest.main()
