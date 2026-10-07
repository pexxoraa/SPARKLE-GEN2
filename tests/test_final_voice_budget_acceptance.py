import unittest
from unittest.mock import patch
from sparkle.model import ModelError
from sparkle.secrets import SecretResolver
from sparkle_gen2.protected_secrets import GEMINI_SECRET_REF
from sparkle_gen2.gemini_voicechat_transport import GeminiLiveVoiceTransport
from test_cycle73_gemini_live_voice import FakeRunner, msg, output_msg

MODULE='sparkle_gen2.infrastructure.providers.voice.gemini_voicechat_transport'

class DelayedRunner(FakeRunner):
    def __init__(self, first_audio=4.0, finish=9.0, never_complete=False, oversized=False, **kwargs):
        super().__init__([msg(transcript='hello',turn_complete=True)],**kwargs)
        self.elapsed=0.0;self.first_audio=first_audio;self.finish=finish;self.never_complete=never_complete;self.oversized=oversized;self.speech=False;self.sent_audio=False
    def send_text(self,text):self.speech=True;self.texts.append(text)
    def recv(self,timeout):
        if not self.speech:return super().recv(timeout)
        self.elapsed+=timeout
        if not self.sent_audio and self.elapsed>=self.first_audio:
            self.sent_audio=True
            return output_msg(audio=(b'\x00\x00'*2_160_001 if self.oversized else b'\x00\x00'*50),turn_complete=False)
        if self.elapsed>=self.finish and not self.never_complete:return msg(turn_complete=True)
        raise TimeoutError('synthetic wait')

class FinalVoiceBudgetAcceptanceTests(unittest.TestCase):
    def transport(self,runner):
        transport=GeminiLiveVoiceTransport(secrets=SecretResolver({GEMINI_SECRET_REF:'test-only'}),secret_refs=[GEMINI_SECRET_REF],runner_factory=lambda **_:runner,turn_timeout=12)
        session={'session_id':'audit','input_audio':{'sample_rate':24000,'channels':1,'sample_width':2,'encoding':'pcm_s16le'},'output_audio':{'sample_rate':24000,'channels':1,'sample_width':2,'encoding':'pcm_s16le'}}
        ref=transport.open_session(session)
        from types import SimpleNamespace
        transport.send_audio(ref,SimpleNamespace(sample_rate=24000,channels=1,sample_width=2,encoding='pcm_s16le',audio=b'\x00\x00',final=True))
        return transport,ref
    def test_delayed_first_audio_and_longer_speech_honor_configured_turn_budget(self):
        runner=DelayedRunner();transport,ref=self.transport(runner)
        with patch(MODULE+'.time.monotonic',side_effect=lambda:runner.elapsed):result=transport.respond_text(ref,'Authorized synthetic response')
        self.assertGreaterEqual(runner.elapsed,9)
        self.assertTrue(result['final'])
        self.assertTrue(result['audio_chunks'][-1]['final'])
    def test_partial_speech_without_turn_completion_is_not_falsely_final(self):
        runner=DelayedRunner(never_complete=True);transport,ref=self.transport(runner)
        with patch(MODULE+'.time.monotonic',side_effect=lambda:runner.elapsed),self.assertRaises(ModelError) as raised:transport.respond_text(ref,'Authorized synthetic response')
        self.assertEqual(raised.exception.category,'timeout')
    def test_provider_audio_flood_is_bounded(self):
        runner=DelayedRunner(oversized=True);transport,ref=self.transport(runner)
        with patch(MODULE+'.time.monotonic',side_effect=lambda:runner.elapsed),self.assertRaises(ModelError) as raised:transport.respond_text(ref,'Authorized synthetic response')
        self.assertEqual(raised.exception.category,'malformed_response')
