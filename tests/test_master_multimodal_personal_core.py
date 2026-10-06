import base64,unittest
from pathlib import Path
from types import SimpleNamespace

from sparkle.model import ModelResponse
from sparkle_gen2.environment_gateway import EnvironmentGateway
from sparkle_gen2.multimodal import MultimodalGateway
from sparkle_gen2.personal_core import PersonalCore


import io
import wave
from PIL import Image

def encoded_image(format):
    output=io.BytesIO()
    with Image.new('RGBA',(8,8),(255,0,0,255)) as picture:
        picture.save(output,format=format,**({'lossless':True} if format=='WEBP' else {}))
    return output.getvalue()

PNG=encoded_image('PNG')
WEBP=encoded_image('WEBP')
_audio=io.BytesIO()
with wave.open(_audio,'wb') as _sound:
    _sound.setnchannels(1);_sound.setsampwidth(2);_sound.setframerate(16000);_sound.writeframes(b'\x00\x00'*160)
WAV=_audio.getvalue()


class Route:
    status='HEALTHY'
    selected=SimpleNamespace(record_id='omni')
    def to_dict(self):return {'status':'HEALTHY','selected':{'record_id':'omni'}}


class FakeManager:
    def __init__(self):self.calls=[]
    def route(self,*args,**kwargs):return Route()
    def complete(self,request,requires,**kwargs):
        self.calls.append((request,requires,kwargs))
        return {'response':ModelResponse('A bounded red square.','omni','nvidia','stop'),'provenance':{'provider':'nvidia','model':'omni','fallback':False}}
class FakeConversations:
    def __init__(self):self.sent=[]
    def send(self,text,**kwargs):
        self.sent.append((text,kwargs))
        return {'session_id':'s1','message':{'text':'done'},'result':{'goal_id':'g1','status':'COMPLETED','text':'done'}}


def core():
    c=PersonalCore.__new__(PersonalCore)
    manager=FakeManager();c.agent=SimpleNamespace(gen1=SimpleNamespace(model_manager=manager))
    c.multimodal=MultimodalGateway();c.conversations=FakeConversations()
    return c,manager


class MasterMultimodalPersonalCoreTests(unittest.TestCase):
    def test_binary_mime_requires_recognized_magic_and_webp_is_detected(self):
        g=MultimodalGateway()
        with self.assertRaisesRegex(ValueError,'does not match'):g.normalize_bytes(b'not-an-image',modality='image',mime_type='image/webp')
        item=g.normalize_bytes(WEBP,modality='image',mime_type='image/webp')
        self.assertEqual((item.modality,item.mime_type),('image','image/webp'))
        self.assertTrue(item.metadata['metadata_stripped'])

    def test_image_bridge_is_bounded_in_memory_and_preserves_model_provenance(self):
        c,m=core();encoded=base64.b64encode(PNG).decode()
        out=c.multimodal_send(modality='image',mime_type='image/png',data_base64=encoded,prompt='What is shown?',device_id='d1')
        self.assertEqual(out['status'],'COMPLETED');self.assertEqual(out['model'],{'provider':'nvidia','model':'omni','fallback':False})
        self.assertEqual(out['media']['size_bytes'],len(PNG));self.assertEqual(len(out['media']['sha256']),64);self.assertTrue(out['media']['metadata_stripped'])
        self.assertEqual(len(m.calls),1);self.assertEqual(len(c.conversations.sent),1)
        persisted=c.conversations.sent[0][0]
        self.assertIn('Image interpretation from nvidia/omni',persisted)
        self.assertNotIn(encoded,persisted)
        self.assertNotIn(PNG.hex(),persisted)

    def test_static_audio_is_routed_to_realtime_voice_session_boundary(self):
        c,m=core();out=c.multimodal_send(modality='audio',mime_type='audio/wav',data_base64=base64.b64encode(WAV).decode(),prompt='listen')
        self.assertEqual(out['status'],'BLOCKED');self.assertEqual(out['reason'],'audio_requires_realtime_voice_session');self.assertEqual(m.calls,[])

    def test_invalid_base64_modality_prompt_and_payload_bounds_fail_closed(self):
        c,_=core()
        with self.assertRaisesRegex(ValueError,'base64'):c.multimodal_send(modality='image',mime_type='image/png',data_base64='***')
        with self.assertRaisesRegex(ValueError,'modality'):c.multimodal_send(modality='video',mime_type='video/mp4',data_base64='eA==')
        with self.assertRaisesRegex(ValueError,'prompt'):c.multimodal_send(modality='image',mime_type='image/png',data_base64=base64.b64encode(PNG).decode(),prompt='x'*2001)
        with self.assertRaisesRegex(ValueError,'too_large'):c.multimodal_send(modality='image',mime_type='image/png',data_base64='A'*5_500_001)

    def test_personal_core_close_uses_existing_connector_lifecycle(self):
        class Connectors:
            def __init__(self):self.calls=0
            def close(self):self.calls+=1;return {'closed_connectors':['gmail','computer']}
        connectors=Connectors();c=PersonalCore.__new__(PersonalCore);c.agent=SimpleNamespace(connectors=connectors)
        out=c.close();self.assertEqual(out,{'status':'closed','connectors':['gmail','computer']});self.assertEqual(connectors.calls,1)

    def test_environment_gateway_forwards_model_capability_interfaces(self):
        base=SimpleNamespace(model_manager='manager',capability_router='router');env=EnvironmentGateway(base)
        self.assertEqual(env.model_manager,'manager');self.assertEqual(env.capability_router,'router')

    def test_pwa_exposes_bounded_image_and_live_voice_controls(self):
        root=Path('src/sparkle_gen2/web');html=(root/'index.html').read_text();js='\n'.join([p.read_text() for p in (root/'ui'/'modules').glob('*.js')])
        self.assertIn('id="image-upload"',html);self.assertIn('accept="image/png,image/jpeg,image/webp"',html);self.assertIn('id="voice-button"',html)
        self.assertIn('id="voice-button"',html);self.assertIn('Start live voice conversation',html)
        self.assertNotIn('Voice is blocked until the real VoiceChat realtime transport is verified',html)
        self.assertIn("file.size>4000000",js);self.assertIn("api('/api/multimodal'",js);self.assertIn("modality:'image'",js)
        self.assertIn("navigator.mediaDevices.getUserMedia",js);self.assertIn("resampleVoicePcm16",js);self.assertIn("api('/api/voice/status'",js)
        self.assertIn("/api/voice/sessions/",js);self.assertIn("audio_base64",js);self.assertIn("offset+=48000",js);self.assertIn("handleVoicePayload",js)

if __name__=='__main__':unittest.main()
