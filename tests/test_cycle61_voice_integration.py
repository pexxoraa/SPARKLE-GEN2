import io,json,tempfile,unittest,uuid,wave
from pathlib import Path

from sparkle.model import ModelAdapter
from sparkle.secrets import SecretResolver
from sparkle.system import SparkleSystem
from sparkle_gen2.conversations import ConversationService
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.gen1 import LocalGen1Gateway
from sparkle_gen2.model_manager import ModelCapabilityManager,build_gen2_model_registry
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.notification_delivery import NotificationDeliveryOrchestrator
from sparkle_gen2.notifications import NotificationCenter,NotificationIntelligenceService
from sparkle_gen2.nvidia_models import NVIDIAVoiceChatAdapter
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.sessions import SessionService
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.voice_runtime import VoiceAudioChunk,VoiceInputFrame,VoiceProviderResult,VoiceSessionService,VoiceSessionState,VoiceTranscriptEvent
from sparkle_gen2.core_time import now

class FakeVoiceTransport:
    def __init__(self,*,transcript='hello sparkle',fail_send=False,early_audio=False,bad_audio=False):self.transcript=transcript;self.fail_send=fail_send;self.early_audio=early_audio;self.bad_audio=bad_audio;self.opened=[];self.spoken=[];self.interrupted=[];self.closed=[]
    def open_session(self,session):self.opened.append(dict(session));return 'provider-session-1'
    def send_audio(self,ref,frame):
        if self.fail_send:raise TimeoutError('provider timeout')
        transcripts=[VoiceTranscriptEvent('heard',frame.session_id,'user',self.transcript,True,now(),'provider-heard')]
        chunks=[VoiceAudioChunk(frame.session_id,0,b'\x00\x00',now())] if self.early_audio else []
        return VoiceProviderResult(frame.session_id,tuple(transcripts),tuple(chunks),'provider-input-1',True)
    def respond_text(self,ref,text):
        self.spoken.append(text)
        if self.bad_audio:return {'audio_chunks':[{'audio':b'\x00\x00','sample_rate':16000,'channels':1,'sample_width':2,'encoding':'pcm_s16le'}],'provider_request_id':'bad'}
        return VoiceProviderResult('SESSION_PLACEHOLDER')
    def interrupt(self,ref):self.interrupted.append(ref);return {'interrupted':True}
    def close_session(self,ref):self.closed.append(ref);return {'closed':True}

class SessionAwareTransport(FakeVoiceTransport):
    def open_session(self,session):self.sid=session['session_id'];return super().open_session(session)
    def respond_text(self,ref,text):
        self.spoken.append(text)
        rate=16000 if self.bad_audio else 24000
        return {'audio_chunks':[{'audio':b'\x00\x00\x01\x00','sample_rate':rate,'channels':1,'sample_width':2,'encoding':'pcm_s16le','final':True,'provider_reference':'out-1'}],'provider_request_id':'provider-output-1','final':True}

class Cycle61VoiceTests(unittest.TestCase):
    def voice_cfg(self):
        return {'model_id':'nvidia/nemotron-voicechat','secret_refs':['NEMOTRON_VOICECHAT_API_KEY'],'enabled':True,'transport_verified':False,'function_id':'42c86b5f-545a-4b2f-a83b-90fd71da9912','function_version':'bfaa0774-00e3-43d3-ae4e-254c4f9be49c'}
    def manager_with_transport(self,transport):
        p=Path(__file__).parents[1]/'src/sparkle_gen2/nemotron_models.json';secrets=SecretResolver({'NEMOTRON_VOICECHAT_API_KEY':'test-only','NVIDIA_API_KEY':'test-only'});r=build_gen2_model_registry(path=p,secrets=secrets);adapter=NVIDIAVoiceChatAdapter(self.voice_cfg(),secrets,transport=transport);r.inject('nvidia-nemotron-voicechat',adapter);return ModelCapabilityManager(registry=r,fallback_allowed=False)
    def pcm(self,sid='s',sequence=0,final=True):return VoiceInputFrame(sid,sequence,b'\x00\x00'*160,now(),final=final)

    def test_registry_voice_record_is_nvidia_streaming_audio_text_no_fallback_and_transport_gated(self):
        d=json.loads((Path(__file__).parents[1]/'src/sparkle_gen2/nemotron_models.json').read_text());v=next(x for x in d['models'] if x['id']=='nvidia-nemotron-voicechat');self.assertEqual(v['provider'],'nvidia');self.assertEqual(v['model_id'],'nvidia/nemotron-voicechat');self.assertEqual(v['capabilities'],['voice']);self.assertEqual(v['input_modalities'],['audio','text']);self.assertEqual(v['output_modalities'],['text','audio']);self.assertTrue(v['supports_streaming']);self.assertFalse(v['allow_fallback']);self.assertEqual(v['secret_refs'],['NEMOTRON_VOICECHAT_API_KEY']);self.assertTrue(v['requires_verified_transport']);self.assertFalse(v['transport_verified']);self.assertNotIn('base_url',v);self.assertEqual(d['routing']['voice'],'google-gemini-3.8-live')
        r=build_gen2_model_registry(path=Path(__file__).parents[1]/'src/sparkle_gen2/nemotron_models.json',secrets=SecretResolver({'NEMOTRON_VOICECHAT_API_KEY':'test-only','NVIDIA_API_KEY':'test-only'}));m=ModelCapabilityManager(registry=r,fallback_allowed=False);self.assertIsNone(m.route(['voice'],input_modalities=['audio'],output_modalities=['audio','text']).selected);self.assertEqual(m.status('voice')['status'],'EXTERNALLY_BLOCKED')

    def test_injected_verified_transport_routes_voice_without_hijacking_reasoning(self):
        m=self.manager_with_transport(SessionAwareTransport());voice=m.voice_provider(provider='nvidia')['route'];self.assertEqual(voice['selected']['record_id'],'nvidia-nemotron-voicechat');self.assertFalse(voice['fallback']);reason=m.route(['reasoning'],input_modalities=['text'],output_modalities=['text']);self.assertEqual(reason.selected.record_id,'nvidia-nemotron-3.5-lightning')

    def test_audio_frame_contract_rejects_invalid_rate_channels_width_size_alignment_and_malformed_wav(self):
        for kwargs in ({'sample_rate':8000},{'channels':2},{'sample_width':1},{'encoding':'wav'}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):VoiceInputFrame('s',0,b'\x00\x00',now(),**kwargs)
        with self.assertRaises(ValueError):VoiceInputFrame('s',0,b'x'*(64001),now())
        with self.assertRaises(ValueError):VoiceInputFrame('s',0,b'\x00',now())
        with self.assertRaises(ValueError):VoiceInputFrame.from_wav('s',0,b'not-a-wav')
        buf=io.BytesIO()
        with wave.open(buf,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(b'\x00\x00'*10)
        f=VoiceInputFrame.from_wav('s',0,buf.getvalue());self.assertEqual((f.sample_rate,f.channels,f.sample_width),(24000,1,2))

    def test_output_contract_rejects_wrong_provider_audio_format(self):
        with self.assertRaises(ValueError):VoiceAudioChunk('s',0,b'\x00\x00',now(),sample_rate=22050)
        with self.assertRaises(ValueError):VoiceAudioChunk('s',0,b'\x00\x00',now(),channels=2)
        with self.assertRaises(ValueError):VoiceAudioChunk('s',0,b'\x00',now())

    def test_session_connect_stream_personalagent_response_audio_and_provenance_without_raw_audio_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.db');agent=PersonalAgent(store,LocalGen1Gateway(SparkleSystem()),planner=StaticPlanner(PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('calc','calculate',['calculator'],[],['verified'],{'expression':'2+2'},30,0)],[{'description':'verified','verification_method':'all_steps_verified'}],'LOW',.99,[],now())));conv=ConversationService(store,SessionService(store),agent);t=SessionAwareTransport(transcript='calculate 2+2');svc=VoiceSessionService(store,conversation_service=conv,provider=t,provider_identity={'provider':'nvidia','model':'nvidia/nemotron-voicechat','fallback':False});s=svc.create(owner_user_id='user');connected=svc.connect(s.session_id);self.assertEqual(connected.state,'CONNECTED');frame=VoiceInputFrame(s.session_id,0,b'\x00\x00'*160,now(),final=True);response=svc.push(frame);self.assertEqual(response.state,'ACTIVE');self.assertEqual(response.agent_result['status'],'COMPLETED');self.assertTrue(response.audio_chunks);self.assertEqual(response.audio_chunks[0].sample_rate,24000);self.assertEqual(response.provenance['provider'],'nvidia');self.assertEqual(response.provenance['model'],'nvidia/nemotron-voicechat');self.assertFalse(response.provenance['fallback']);events=store.voice_events(s.session_id);blob=json.dumps(events);self.assertNotIn(str(frame.audio),blob);self.assertTrue(any(x['event_type']=='voice_input_frame' for x in events));self.assertTrue(any(x['event_type']=='voice_agent_response' for x in events));self.assertTrue(t.spoken)

    def test_voice_uses_same_approval_boundary_as_text_and_cannot_execute_before_approval(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.db');delivery=NotificationDeliveryOrchestrator(store);center=NotificationCenter(store);intel=NotificationIntelligenceService(store,center=center,delivery=delivery);dec=intel.process(owner_user_id='user',event_type='background_failure',subject='x',title='x',summary='x failed',source_kind='test',source_id='v',state={'status':'FAILED'});dash=next(x for x in delivery.attempts('user',decision_id=dec.decision_id) if x['channel']=='dashboard')
            plan=PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('ack','ack',['notification_acknowledge'],[],['verified'],{'attempt_id':dash['attempt_id']},30,0)],[{'description':'verified','verification_method':'all_steps_verified'}],'MEDIUM',.99,[],now());agent=PersonalAgent(store,LocalGen1Gateway(SparkleSystem()),planner=StaticPlanner(plan),notification_service=intel);conv=ConversationService(store,SessionService(store),agent);t=SessionAwareTransport(transcript='acknowledge the notification');svc=VoiceSessionService(store,conversation_service=conv,provider=t,provider_identity={'provider':'nvidia','model':'nvidia/nemotron-voicechat','fallback':False});s=svc.create();svc.connect(s.session_id);out=svc.push(VoiceInputFrame(s.session_id,0,b'\x00\x00'*160,now(),final=True));self.assertEqual(out.agent_result['status'],'WAITING');self.assertTrue(out.agent_result['approvals']);self.assertEqual(store.notification_delivery_attempt(dash['attempt_id'])['status'],'ACCEPTED');self.assertEqual(t.spoken,[]);agent.decide_approval(out.agent_result['approvals'][0],'approve',actor='human-reviewer');done=svc.resume_pending(s.session_id);self.assertEqual(done.agent_result['status'],'COMPLETED');self.assertTrue(done.audio_chunks);self.assertTrue(t.spoken);self.assertEqual(store.notification_delivery_attempt(dash['attempt_id'])['status'],'ACKNOWLEDGED')

    def test_provider_audio_before_personalagent_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.db');t=SessionAwareTransport(early_audio=True);svc=VoiceSessionService(store,provider=t);s=svc.create();svc.connect(s.session_id)
            with self.assertRaisesRegex(RuntimeError,'provider_audio_before_personal_agent_authorization'):svc.push(VoiceInputFrame(s.session_id,0,b'\x00\x00',now()))
            self.assertEqual(store.load_voice_session(s.session_id).state,'FAILED')

    def test_sensitive_classification_blocks_external_provider_before_connect(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.db');t=SessionAwareTransport();svc=VoiceSessionService(store,provider=t);s=svc.create(classification='HIGHLY_SENSITIVE');blocked=svc.connect(s.session_id);self.assertEqual(blocked.state,'UNAVAILABLE');self.assertEqual(t.opened,[])

    def test_transcript_can_be_nonpersistent_while_still_reaching_agent(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.db');agent=PersonalAgent(store,LocalGen1Gateway(SparkleSystem()),planner=StaticPlanner(PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('calc','calc',['calculator'],[],['verified'],{'expression':'2+2'},30,0)],[{'description':'verified','verification_method':'all_steps_verified'}],'LOW',.9,[],now())));conv=ConversationService(store,SessionService(store),agent);svc=VoiceSessionService(store,conversation_service=conv,provider=SessionAwareTransport(transcript='calculate 2+2'));s=svc.create(persist_transcript=False);svc.connect(s.session_id);out=svc.push(VoiceInputFrame(s.session_id,0,b'\x00\x00',now()));self.assertEqual(out.agent_result['status'],'COMPLETED');events=store.voice_events(s.session_id);te=next(x for x in events if x['event_type']=='voice_transcript');self.assertNotIn('text',te['payload']);self.assertFalse(te['payload']['text_persisted'])

    def test_provider_failure_malformed_events_and_malformed_audio_fail_session(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.db');svc=VoiceSessionService(store,provider=SessionAwareTransport(fail_send=True));s=svc.create();svc.connect(s.session_id)
            result=svc.push(VoiceInputFrame(s.session_id,0,b'\x00\x00',now()))
            self.assertTrue(result.agent_result['voice_retry'])
            self.assertEqual(result.state,VoiceSessionState.CONNECTED.value)
            self.assertEqual(store.load_voice_session(s.session_id).state,'CONNECTED')
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.db')
            class Bad(SessionAwareTransport):
                def send_audio(self,ref,frame):return {'transcripts':[{'speaker':'alien','text':'x','final':True}]}
            svc=VoiceSessionService(store,provider=Bad());s=svc.create();svc.connect(s.session_id)
            with self.assertRaises(ValueError):svc.push(VoiceInputFrame(s.session_id,0,b'\x00\x00',now()))
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.db');agent=PersonalAgent(store,LocalGen1Gateway(SparkleSystem()),planner=StaticPlanner(PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('calc','calc',['calculator'],[],['verified'],{'expression':'2+2'},30,0)],[{'description':'v','verification_method':'all_steps_verified'}],'LOW',.9,[],now())));conv=ConversationService(store,SessionService(store),agent);svc=VoiceSessionService(store,conversation_service=conv,provider=SessionAwareTransport(transcript='calculate 2+2',bad_audio=True));s=svc.create();svc.connect(s.session_id)
            with self.assertRaises(ValueError):svc.push(VoiceInputFrame(s.session_id,0,b'\x00\x00',now()))

    def test_interruption_cancellation_and_restart_recovery_are_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'g.db';store=Gen2Store(db);t=SessionAwareTransport();svc=VoiceSessionService(store,provider=t);s=svc.create();svc.connect(s.session_id);interrupted=svc.interrupt(s.session_id);self.assertEqual(interrupted.state,'CONNECTED');cancelled=svc.cancel(s.session_id);self.assertEqual(cancelled.state,'CANCELLED');self.assertTrue(t.closed)
            s2=svc.create();svc.connect(s2.session_id);restarted=VoiceSessionService(Gen2Store(db),provider=SessionAwareTransport());recovered=restarted.recover(s2.session_id);self.assertEqual(recovered.state,'UNAVAILABLE');self.assertIn('not_resumable',recovered.failure_reason)

    def test_unresolved_production_transport_and_secret_do_not_report_healthy(self):
        p=Path(__file__).parents[1]/'src/sparkle_gen2/nemotron_models.json';m=ModelCapabilityManager(registry=build_gen2_model_registry(path=p,secrets=SecretResolver({})),fallback_allowed=False);svc=VoiceSessionService(Gen2Store(Path(tempfile.mkdtemp())/'g.db'),model_manager=m);health=svc.health();self.assertEqual(health['status'],'UNAVAILABLE');self.assertFalse(health['live_verified'])

if __name__=='__main__':unittest.main()
