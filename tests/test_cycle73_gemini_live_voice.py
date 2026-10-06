import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from sparkle.secrets import SecretResolver
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.core_time import now
from sparkle_gen2.gen1 import LocalGen1Gateway
from sparkle_gen2.model_manager import ModelCapabilityManager, build_gen2_model_registry
from sparkle_gen2.notifications import NotificationCenter, NotificationIntelligenceService
from sparkle_gen2.notification_delivery import NotificationDeliveryOrchestrator
from sparkle_gen2.models import PlanProposal, PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.personal_core import PersonalCore
from sparkle_gen2.protected_secrets import (
    GEMINI_SECRET_REF,
    protected_gemini_environment,
    protected_voice_provider,
)
from sparkle_gen2.sessions import SessionService
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.conversations import ConversationService
from sparkle_gen2.voice_runtime import VoiceInputFrame, VoiceSessionService
from sparkle_gen2.gemini_voicechat_transport import (
    GEMINI_INPUT_RATE,
    GEMINI_LIVE_MODEL,
    GEMINI_OUTPUT_RATE,
    PERSONAL_AGENT_TOOL,
    GeminiLiveVoiceAdapter,
    GeminiLiveVoiceTransport,
)


def msg(*, transcript=None, audio=None, tool=None, turn_complete=False, interrupted=False, cancellation=None):
    parts=[]
    if audio is not None:
        parts=[SimpleNamespace(inline_data=SimpleNamespace(data=audio))]
    content=None
    if transcript is not None or audio is not None or turn_complete or interrupted:
        content=SimpleNamespace(
            input_transcription=SimpleNamespace(text=transcript) if transcript is not None else None,
            output_transcription=None,
            model_turn=SimpleNamespace(parts=parts) if parts else None,
            turn_complete=turn_complete,
            generation_complete=False,
            interrupted=interrupted,
        )
    tool_call=None
    if tool is not None:
        tool_call=SimpleNamespace(function_calls=[SimpleNamespace(**tool)])
    cancel=SimpleNamespace(ids=list(cancellation)) if cancellation is not None else None
    return SimpleNamespace(server_content=content,tool_call=tool_call,tool_call_cancellation=cancel)


def output_msg(audio=b"\x01\x00"*80,text="done",turn_complete=True):
    return SimpleNamespace(
        server_content=SimpleNamespace(
            input_transcription=None,
            output_transcription=SimpleNamespace(text=text),
            model_turn=SimpleNamespace(parts=[SimpleNamespace(inline_data=SimpleNamespace(data=audio))]),
            turn_complete=turn_complete,
            generation_complete=False,
            interrupted=False,
        ),
        tool_call=None,
        tool_call_cancellation=None,
    )


class FakeRunner:
    def __init__(self, events=None, **kwargs):
        self.events=list(events or [])
        self.config=kwargs.get("config")
        self.key_present=bool(kwargs.get("api_key"))
        self.audio=[]
        self.ended=False
        self.responses=[]
        self.on_response=[]
        self.interrupted=False
        self.closed=False
        self.activities=[]
        self.texts=[]
    def start_activity(self):self.activities.append('start')
    def send_audio(self,audio):self.audio.append(bytes(audio))
    def end_audio(self):self.ended=True;self.activities.append('end')
    def send_text(self,text):self.texts.append(str(text));self.events.extend(self.on_response)
    def recv(self,timeout):
        if not self.events:raise TimeoutError("empty")
        return self.events.pop(0)
    def recv_nowait(self):
        return self.events.pop(0) if self.events else None
    def send_tool_response(self,call_id,name,text):self.responses.append((call_id,name,text));self.texts.append(str(text));self.events.extend(self.on_response)
    def interrupt(self):self.interrupted=True;self.events.append(msg(turn_complete=True))
    def drain(self):n=len(self.events);self.events.clear();return n
    def close(self):self.closed=True


class RunnerFactory:
    def __init__(self,*event_sets):self.event_sets=list(event_sets);self.runners=[]
    def __call__(self,**kwargs):
        events=self.event_sets.pop(0) if self.event_sets else []
        runner=FakeRunner(events,**kwargs);self.runners.append(runner);return runner


class GeminiLiveVoiceTests(unittest.TestCase):
    def config(self,transport_verified=False):
        return {
            "model_id":GEMINI_LIVE_MODEL,
            "secret_refs":[GEMINI_SECRET_REF],
            "enabled":True,
            "transport_verified":transport_verified,
            "transport_kind":"google_genai_live_sdk",
        }
    def session(self):
        return {
            "session_id":"s1",
            "input_audio":{"sample_rate":24000,"channels":1,"sample_width":2,"encoding":"pcm_s16le"},
            "output_audio":{"sample_rate":24000,"channels":1,"sample_width":2,"encoding":"pcm_s16le"},
        }
    def frame(self,sid="s1",final=True):
        return SimpleNamespace(sample_rate=24000,channels=1,sample_width=2,encoding="pcm_s16le",audio=b"\x00\x00"*480,final=final,session_id=sid)

    def test_protected_gemini_secret_and_provider_setting_are_owner_only(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"gen2.env";p.write_text("GEMINI_API_KEY=unit-secret\nVOICE_PROVIDER=gemini\nNVIDIA_API_KEY=other\n");p.chmod(0o600)
            env,status=protected_gemini_environment(base={},path=p)
            self.assertEqual(set(env),{GEMINI_SECRET_REF})
            self.assertTrue(status.credential_value_loaded)
            self.assertEqual(protected_voice_provider(base={},path=p),"gemini")
            p.chmod(0o644)
            env,status=protected_gemini_environment(base={},path=p)
            self.assertNotIn(GEMINI_SECRET_REF,env);self.assertFalse(status.credential_value_loaded)
            self.assertIsNone(protected_voice_provider(base={},path=p))

    def test_config_uses_explicit_activity_boundaries_and_blocking_authority(self):
        factory=RunnerFactory([])
        transport=GeminiLiveVoiceTransport(secrets=SecretResolver({GEMINI_SECRET_REF:"unit"}),secret_refs=[GEMINI_SECRET_REF],runner_factory=factory)
        ref=transport.open_session(self.session());cfg=factory.runners[0].config
        self.assertNotIn("tools",cfg)
        self.assertEqual(cfg["max_output_tokens"],40)
        self.assertTrue(cfg["realtime_input_config"]["automatic_activity_detection"]["disabled"])
        self.assertIn("input_audio_transcription",cfg);self.assertIn("output_audio_transcription",cfg);self.assertNotIn("thinking_config",cfg)
        self.assertIn("SPARKLE owns policy",cfg["system_instruction"])
        transport.close_session(ref)

    def test_provider_boundary_resamples_24khz_to_16khz_and_never_exposes_pretool_audio(self):
        pre=b"\x02\x00"*40
        factory=RunnerFactory([
            msg(audio=pre),
            msg(transcript="calculate two plus two"),
            msg(tool={"id":"c1","name":PERSONAL_AGENT_TOOL,"args":{}}),
        ])
        transport=GeminiLiveVoiceTransport(secrets=SecretResolver({GEMINI_SECRET_REF:"unit"}),secret_refs=[GEMINI_SECRET_REF],runner_factory=factory)
        ref=transport.open_session(self.session());result=transport.send_audio(ref,self.frame())
        self.assertEqual(result["audio_chunks"],[])
        self.assertEqual(result["transcripts"][0]["text"],"calculate two plus two")
        self.assertGreater(result["pre_authorization_audio_bytes"],0)
        sent=sum(len(x) for x in factory.runners[0].audio)
        self.assertGreater(sent,0);self.assertLess(sent,len(self.frame().audio))
        self.assertEqual(GEMINI_INPUT_RATE,16000);self.assertEqual(GEMINI_OUTPUT_RATE,24000)

    def test_partial_transcripts_are_assembled_before_authorization(self):
        factory=RunnerFactory([
            msg(transcript="What"),
            msg(tool={"id":"c1","name":PERSONAL_AGENT_TOOL,"args":{}}),
            msg(transcript="is Python programming?",turn_complete=True),
        ])
        transport=GeminiLiveVoiceTransport(secrets=SecretResolver({GEMINI_SECRET_REF:"unit"}),secret_refs=[GEMINI_SECRET_REF],runner_factory=factory)
        ref=transport.open_session(self.session());result=transport.send_audio(ref,self.frame())
        self.assertEqual(result["transcripts"][0]["text"],"What is Python programming?")
        self.assertTrue(transport.validate_pending_call(ref)["valid"])

    def test_finalized_transcript_is_cleared_between_turns(self):
        factory=RunnerFactory([msg(transcript='Add a new task complete C++ learning.'),msg(turn_complete=True)])
        transport=GeminiLiveVoiceTransport(secrets=SecretResolver({GEMINI_SECRET_REF:'unit'}),secret_refs=[GEMINI_SECRET_REF],runner_factory=factory)
        ref=transport.open_session(self.session());first=transport.send_audio(ref,self.frame())
        self.assertEqual(first['transcripts'][0]['text'],'Add a new task complete C++ learning.')
        state=transport._state(ref)
        self.assertEqual(state.input_transcript,'')

    def test_provider_output_before_authorization_is_discarded(self):
        factory=RunnerFactory([msg(transcript="hello",audio=b"\x00\x00"*40),msg(tool={"id":"c1","name":PERSONAL_AGENT_TOOL,"args":{}})])
        transport=GeminiLiveVoiceTransport(secrets=SecretResolver({GEMINI_SECRET_REF:"unit"}),secret_refs=[GEMINI_SECRET_REF],runner_factory=factory)
        ref=transport.open_session(self.session());result=transport.send_audio(ref,self.frame())
        self.assertEqual(result["audio_chunks"],[]);self.assertGreater(result["pre_authorization_audio_bytes"],0)

    def test_missing_model_gate_falls_back_to_sparkle_owned_authorization(self):
        factory=RunnerFactory([msg(transcript="What is Python programming?"),msg(turn_complete=True)])
        transport=GeminiLiveVoiceTransport(secrets=SecretResolver({GEMINI_SECRET_REF:"unit"}),secret_refs=[GEMINI_SECRET_REF],runner_factory=factory)
        ref=transport.open_session(self.session());result=transport.send_audio(ref,self.frame())
        self.assertEqual(result["transcripts"][0]["text"],"What is Python programming?")
        self.assertEqual(result["audio_chunks"],[])
        self.assertTrue(transport.validate_pending_call(ref)["valid"])
        factory.runners[0].on_response=[output_msg(text="authorized")]
        spoken=transport.respond_text(ref,"Authorized answer.")
        self.assertTrue(spoken["audio_chunks"]);self.assertEqual(factory.runners[0].texts,["Authorized answer."])

    def test_authorized_text_is_the_only_speech_trigger(self):
        factory=RunnerFactory([msg(transcript="hello"),msg(tool={"id":"c1","name":PERSONAL_AGENT_TOOL,"args":{}})])
        transport=GeminiLiveVoiceTransport(secrets=SecretResolver({GEMINI_SECRET_REF:"unit"}),secret_refs=[GEMINI_SECRET_REF],runner_factory=factory)
        ref=transport.open_session(self.session());transport.send_audio(ref,self.frame())
        factory.runners[0].on_response=[output_msg(text="authorized")]
        spoken=transport.respond_text(ref,"authorized response")
        self.assertTrue(spoken["audio_chunks"]);self.assertEqual(factory.runners[0].texts,["authorized response"])
        with self.assertRaises(PermissionError):transport.respond_text(ref,"unauthorized second response")

    def test_respond_text_requires_prior_transcript_authorization(self):
        factory=RunnerFactory([])
        transport=GeminiLiveVoiceTransport(secrets=SecretResolver({GEMINI_SECRET_REF:"unit"}),secret_refs=[GEMINI_SECRET_REF],runner_factory=factory)
        ref=transport.open_session(self.session())
        with self.assertRaises(PermissionError):transport.respond_text(ref,"forbidden")

    def test_authorized_speech_returns_only_24khz_audio(self):
        factory=RunnerFactory([
            msg(transcript="calculate two plus two"),
            msg(tool={"id":"c1","name":PERSONAL_AGENT_TOOL,"args":{}}),
        ])
        transport=GeminiLiveVoiceTransport(secrets=SecretResolver({GEMINI_SECRET_REF:"unit"}),secret_refs=[GEMINI_SECRET_REF],runner_factory=factory)
        ref=transport.open_session(self.session());heard=transport.send_audio(ref,self.frame());self.assertEqual(heard["audio_chunks"],[])
        factory.runners[0].on_response=[output_msg(text="four")]
        spoken=transport.respond_text(ref,"The answer is four.")
        self.assertTrue(spoken["audio_chunks"]);self.assertEqual(spoken["audio_chunks"][0]["sample_rate"],24000)
        self.assertEqual(factory.runners[0].texts,["The answer is four."])

    def test_interrupt_discards_session_output_and_clears_authorization(self):
        factory=RunnerFactory([msg(transcript="hello")])
        transport=GeminiLiveVoiceTransport(secrets=SecretResolver({GEMINI_SECRET_REF:"unit"}),secret_refs=[GEMINI_SECRET_REF],runner_factory=factory)
        ref=transport.open_session(self.session());transport.send_audio(ref,self.frame());result=transport.interrupt(ref)
        self.assertTrue(result["interrupted"]);self.assertFalse(result["pending_call_cancelled"]);self.assertTrue(factory.runners[0].interrupted)
        with self.assertRaises(PermissionError):transport.respond_text(ref,"should not send")

    def test_two_sessions_are_isolated(self):
        factory=RunnerFactory(
            [msg(transcript="one"),msg(tool={"id":"c1","name":PERSONAL_AGENT_TOOL,"args":{}})],
            [msg(transcript="two"),msg(tool={"id":"c2","name":PERSONAL_AGENT_TOOL,"args":{}})],
        )
        transport=GeminiLiveVoiceTransport(secrets=SecretResolver({GEMINI_SECRET_REF:"unit"}),secret_refs=[GEMINI_SECRET_REF],runner_factory=factory)
        r1=transport.open_session(self.session());s2=self.session();s2["session_id"]="s2";r2=transport.open_session(s2)
        a=transport.send_audio(r1,self.frame("s1"));b=transport.send_audio(r2,self.frame("s2"))
        self.assertEqual(a["transcripts"][0]["text"],"one");self.assertEqual(b["transcripts"][0]["text"],"two")
        self.assertNotEqual(r1,r2)

    def test_adapter_gate_and_explicit_provider_selection(self):
        resolver=SecretResolver({GEMINI_SECRET_REF:"unit"})
        adapter=GeminiLiveVoiceAdapter(self.config(False),resolver)
        self.assertFalse(adapter.health()["transport_verified"])
        self.assertFalse(adapter.health()["supports_tools"])
        self.assertEqual(adapter.health()["function_behavior"],"SPARKLE_OWNED_AUTHORIZATION")
        with self.assertRaises(Exception):adapter.open_session(self.session())
        factory=RunnerFactory([])
        live=GeminiLiveVoiceAdapter(self.config(False),resolver,transport=GeminiLiveVoiceTransport(secrets=resolver,secret_refs=[GEMINI_SECRET_REF],runner_factory=factory))
        registry=build_gen2_model_registry(secrets=resolver);registry.inject("google-gemini-3.8-live",live)
        manager=ModelCapabilityManager(registry=registry,fallback_allowed=False)
        routed=manager.voice_provider(provider="gemini")
        self.assertEqual(routed["provenance"]["provider"],"google");self.assertEqual(routed["provenance"]["model"],GEMINI_LIVE_MODEL)
        self.assertFalse(routed["route"]["required_input_modalities"] is None and True)

    def test_long_voice_result_is_compacted_into_structured_digest(self):
        text='1. Encapsulation: Bundles data and methods together in a class with controlled access. 2. Abstraction: Hides implementation details and exposes a simple interface. 3. Inheritance: A derived class reuses behavior from a base class. 4. Polymorphism: One interface can represent multiple concrete implementations. 5. Practice: Write a small class and test each principle.'
        digest=VoiceSessionService._voice_digest(text,max_words=30)
        self.assertLessEqual(len(digest.split()),90)
        self.assertIn('I organized the full answer in the conversation panel.',digest)
        self.assertIn('1.',digest);self.assertIn('2.',digest)

    def test_waiting_approval_does_not_send_function_response_until_resume(self):
        class GateTransport:
            def __init__(self):self.responded=[];self.validations=0;self.sid=None
            def open_session(self,session):self.sid=session["session_id"];return "g1"
            def send_audio(self,ref,frame):return {"transcripts":[{"speaker":"user","text":"acknowledge the notification","final":True}],"audio_chunks":[],"provider_request_id":"in","final":True}
            def validate_pending_call(self,ref):self.validations+=1;return {"valid":True}
            def respond_text(self,ref,text):self.responded.append(text);return {"audio_chunks":[{"audio":b"\x01\x00"*20,"sample_rate":24000,"channels":1,"sample_width":2,"encoding":"pcm_s16le","final":True}],"provider_request_id":"out","final":True}
            def interrupt(self,ref):return {"interrupted":True}
            def close_session(self,ref):return {"closed":True}
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/"g.db");delivery=NotificationDeliveryOrchestrator(store);center=NotificationCenter(store);intel=NotificationIntelligenceService(store,center=center,delivery=delivery)
            dec=intel.process(owner_user_id="user",event_type="background_failure",subject="x",title="x",summary="x failed",source_kind="test",source_id="g",state={"status":"FAILED"})
            dash=next(x for x in delivery.attempts("user",decision_id=dec.decision_id) if x["channel"]=="dashboard")
            plan=PlanProposal(uuid.uuid4().hex,"x",[PlanProposalStep("ack","ack",["notification_acknowledge"],[],["verified"],{"attempt_id":dash["attempt_id"]},30,0)],[{"description":"verified","verification_method":"all_steps_verified"}],"MEDIUM",.99,[],now())
            agent=PersonalAgent(store,LocalGen1Gateway(),planner=StaticPlanner(plan),notification_service=intel);conv=ConversationService(store,SessionService(store),agent);transport=GateTransport();svc=VoiceSessionService(store,conversation_service=conv,provider=transport,provider_identity={"provider":"google","model":GEMINI_LIVE_MODEL,"fallback":False})
            s=svc.create();svc.connect(s.session_id);out=svc.push(VoiceInputFrame(s.session_id,0,b"\x00\x00"*160,now(),final=True))
            self.assertEqual(out.agent_result["status"],"WAITING");self.assertEqual(out.audio_chunks,[]);self.assertEqual(transport.responded,[])
            approval=out.agent_result["approvals"][0];agent.decide_approval(approval,"approve",actor="human-reviewer");done=svc.resume_pending(s.session_id)
            self.assertEqual(done.agent_result["status"],"COMPLETED");self.assertTrue(done.audio_chunks);self.assertEqual(len(transport.responded),1)
            events=store.voice_events(s.session_id);self.assertTrue(any(x["event_type"]=="voice_agent_waiting" for x in events));self.assertNotIn("raw_audio",json.dumps(events))


    def test_generic_personal_core_approval_resumes_voice_without_operations_scope(self):
        class GateTransport:
            def __init__(self):self.responded=[]
            def open_session(self,session):return "g1"
            def send_audio(self,ref,frame):return {"transcripts":[{"speaker":"user","text":"acknowledge the notification","final":True}],"audio_chunks":[],"provider_request_id":"in","final":True}
            def validate_pending_call(self,ref):return {"valid":True}
            def respond_text(self,ref,text):self.responded.append(text);return {"audio_chunks":[{"audio":b"\x01\x00"*20,"sample_rate":24000,"channels":1,"sample_width":2,"encoding":"pcm_s16le","final":True}],"provider_request_id":"out","final":True}
            def interrupt(self,ref):return {"interrupted":True}
            def close_session(self,ref):return {"closed":True}
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/"g.db");delivery=NotificationDeliveryOrchestrator(store);center=NotificationCenter(store);intel=NotificationIntelligenceService(store,center=center,delivery=delivery)
            dec=intel.process(owner_user_id="user",event_type="background_failure",subject="x",title="x",summary="x failed",source_kind="test",source_id="generic-approval",state={"status":"FAILED"})
            dash=next(x for x in delivery.attempts("user",decision_id=dec.decision_id) if x["channel"]=="dashboard")
            plan=PlanProposal(uuid.uuid4().hex,"x",[PlanProposalStep("ack","ack",["notification_acknowledge"],[],["verified"],{"attempt_id":dash["attempt_id"]},30,0)],[{"description":"verified","verification_method":"all_steps_verified"}],"MEDIUM",.99,[],now())
            agent=PersonalAgent(store,LocalGen1Gateway(),planner=StaticPlanner(plan),notification_service=intel);conv=ConversationService(store,SessionService(store),agent);transport=GateTransport();svc=VoiceSessionService(store,conversation_service=conv,provider=transport,provider_identity={"provider":"google","model":GEMINI_LIVE_MODEL,"fallback":False})
            session=svc.create();svc.connect(session.session_id);waiting=svc.push(VoiceInputFrame(session.session_id,0,b"\x00\x00"*160,now(),final=True));approval_id=waiting.agent_result["approvals"][0]
            core=PersonalCore.__new__(PersonalCore);core.store=store;core.agent=agent;core.voice=svc
            result=core.decide_approval(approval_id,"approve",owner_user_id="user",actor="browser-device")
            self.assertNotIn("snapshot",result);self.assertEqual(result["goal"]["status"],"COMPLETED");self.assertEqual(result["approval"]["status"],"APPROVED")
            self.assertEqual(len(result["voice"]),1);self.assertTrue(result["voice"][0]["audio_chunks"]);self.assertIn("audio_base64",result["voice"][0]["audio_chunks"][0]);self.assertEqual(len(transport.responded),1)

    def test_post_approval_argument_mutation_is_blocked_before_execution(self):
        class GateTransport:
            def __init__(self):self.responded=[]
            def open_session(self,session):return "g1"
            def send_audio(self,ref,frame):return {"transcripts":[{"speaker":"user","text":"acknowledge the notification","final":True}],"audio_chunks":[],"provider_request_id":"in","final":True}
            def validate_pending_call(self,ref):return {"valid":True}
            def respond_text(self,ref,text):self.responded.append(text);return {"audio_chunks":[{"audio":b"\x01\x00"*20,"sample_rate":24000,"channels":1,"sample_width":2,"encoding":"pcm_s16le","final":True}],"provider_request_id":"out","final":True}
            def interrupt(self,ref):return {"interrupted":True}
            def close_session(self,ref):return {"closed":True}
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/"g.db");delivery=NotificationDeliveryOrchestrator(store);center=NotificationCenter(store);intel=NotificationIntelligenceService(store,center=center,delivery=delivery)
            dec=intel.process(owner_user_id="user",event_type="background_failure",subject="x",title="x",summary="x failed",source_kind="test",source_id="mutation",state={"status":"FAILED"});dash=next(x for x in delivery.attempts("user",decision_id=dec.decision_id) if x["channel"]=="dashboard")
            plan=PlanProposal(uuid.uuid4().hex,"x",[PlanProposalStep("ack","ack",["notification_acknowledge"],[],["verified"],{"attempt_id":dash["attempt_id"]},30,0)],[{"description":"verified","verification_method":"all_steps_verified"}],"MEDIUM",.99,[],now())
            agent=PersonalAgent(store,LocalGen1Gateway(),planner=StaticPlanner(plan),notification_service=intel);conv=ConversationService(store,SessionService(store),agent);transport=GateTransport();svc=VoiceSessionService(store,conversation_service=conv,provider=transport,provider_identity={"provider":"google","model":GEMINI_LIVE_MODEL,"fallback":False})
            s=svc.create();svc.connect(s.session_id);waiting=svc.push(VoiceInputFrame(s.session_id,0,b"\x00\x00"*160,now(),final=True));approval_id=waiting.agent_result["approvals"][0]
            approval=store.load_approval(approval_id);self.assertIn(dash["attempt_id"],approval.requested_scope);agent.decide_approval(approval_id,"approve",actor="human-reviewer")
            goal=store.load_goal(waiting.agent_result["goal_id"]);persisted=store.load_plan(goal.plan_id);persisted.steps[0].arguments={"attempt_id":"mutated-after-approval"};store.save_plan(persisted)
            blocked=svc.resume_pending(s.session_id);self.assertEqual(blocked.agent_result["status"],"BLOCKED");self.assertEqual(store.notification_delivery_attempt(dash["attempt_id"])["status"],"ACCEPTED")
            events=store.recent_events(100);self.assertTrue(any(x["event_type"]=="approval_scope_mismatch" for x in events))


if __name__=="__main__":
    unittest.main()
