from __future__ import annotations
import io,uuid,wave
from dataclasses import asdict,dataclass,field
from enum import StrEnum
from typing import Any
from .core_time import now

VOICE_CLASSIFICATIONS=frozenset({'PUBLIC','PRIVATE','SENSITIVE','HIGHLY_SENSITIVE','DEVICE_CONTROL'})
BLOCKED_EXTERNAL_CLASSIFICATIONS=frozenset({'SENSITIVE','HIGHLY_SENSITIVE','DEVICE_CONTROL'})
INPUT_RATE=16000
OUTPUT_RATE=22050
MAX_FRAME_BYTES=64000
MAX_TRANSCRIPT_CHARS=16000

class VoiceSessionState(StrEnum):
    CREATED='CREATED';CONNECTING='CONNECTING';CONNECTED='CONNECTED';ACTIVE='ACTIVE';STOPPING='STOPPING';COMPLETED='COMPLETED';FAILED='FAILED';UNAVAILABLE='UNAVAILABLE';CANCELLED='CANCELLED'

@dataclass(slots=True)
class VoiceSession:
    session_id:str;owner_user_id:str;state:str;created_at:str;updated_at:str
    conversation_session_id:str|None=None;classification:str='PRIVATE';provider:str|None=None;model:str|None=None;provider_session_reference:str|None=None;fallback:bool=False;persist_transcript:bool=True;failure_reason:str|None=None;outcome:str|None=None;provenance:dict[str,Any]=field(default_factory=dict)
    def to_dict(self):return asdict(self)

@dataclass(frozen=True,slots=True)
class VoiceInputFrame:
    session_id:str;sequence:int;audio:bytes;timestamp:str;sample_rate:int=INPUT_RATE;channels:int=1;sample_width:int=2;encoding:str='pcm_s16le';final:bool=False
    def __post_init__(self):
        if not isinstance(self.audio,(bytes,bytearray)) or not self.audio:raise ValueError('voice audio payload required')
        if self.sample_rate!=INPUT_RATE:raise ValueError('voice input sample_rate must be 16000 Hz')
        if self.channels!=1:raise ValueError('voice input must be mono')
        if self.sample_width!=2:raise ValueError('voice input sample_width must be 16-bit')
        if self.encoding!='pcm_s16le':raise ValueError('voice input encoding must be pcm_s16le')
        if not isinstance(self.sequence,int) or self.sequence<0:raise ValueError('voice frame sequence invalid')
        if len(self.audio)>MAX_FRAME_BYTES:raise ValueError('voice frame exceeds bounded payload size')
        if len(self.audio)%(self.channels*self.sample_width):raise ValueError('voice audio frame is not sample aligned')
    def metadata(self):return {'session_id':self.session_id,'sequence':self.sequence,'timestamp':self.timestamp,'sample_rate':self.sample_rate,'channels':self.channels,'sample_width':self.sample_width,'encoding':self.encoding,'bytes':len(self.audio),'final':self.final}
    @classmethod
    def from_wav(cls,session_id,sequence,wav_bytes,*,timestamp=None,final=True):
        try:
            with wave.open(io.BytesIO(wav_bytes),'rb') as w:
                channels=w.getnchannels();width=w.getsampwidth();rate=w.getframerate();frames=w.readframes(w.getnframes());ctype=w.getcomptype()
        except (wave.Error,EOFError) as exc:raise ValueError('malformed WAV audio') from exc
        if ctype!='NONE':raise ValueError('compressed WAV audio is not supported')
        return cls(session_id,sequence,frames,timestamp or now(),rate,channels,width,'pcm_s16le',final)

@dataclass(frozen=True,slots=True)
class VoiceTranscriptEvent:
    event_id:str;session_id:str;speaker:str;text:str;final:bool;timestamp:str;provider_reference:str|None=None
    def __post_init__(self):
        if self.speaker not in {'user','assistant'}:raise ValueError('voice transcript speaker invalid')
        if not isinstance(self.text,str) or not self.text.strip() or len(self.text)>MAX_TRANSCRIPT_CHARS:raise ValueError('voice transcript text invalid')
    def to_dict(self):return asdict(self)

@dataclass(frozen=True,slots=True)
class VoiceAudioChunk:
    session_id:str;sequence:int;audio:bytes;timestamp:str;sample_rate:int=OUTPUT_RATE;channels:int=1;sample_width:int=2;encoding:str='pcm_s16le';final:bool=False;provider_reference:str|None=None
    def __post_init__(self):
        if not isinstance(self.audio,(bytes,bytearray)) or not self.audio:raise ValueError('voice output audio required')
        if self.sample_rate!=OUTPUT_RATE:raise ValueError('voice output sample_rate must be 22050 Hz')
        if self.channels!=1 or self.sample_width!=2 or self.encoding!='pcm_s16le':raise ValueError('voice output audio format invalid')
        if not isinstance(self.sequence,int) or self.sequence<0 or len(self.audio)>MAX_FRAME_BYTES or len(self.audio)%(self.channels*self.sample_width):raise ValueError('voice output chunk invalid')
    def metadata(self):return {'session_id':self.session_id,'sequence':self.sequence,'timestamp':self.timestamp,'sample_rate':self.sample_rate,'channels':self.channels,'sample_width':self.sample_width,'encoding':self.encoding,'bytes':len(self.audio),'final':self.final,'provider_reference':self.provider_reference}

@dataclass(frozen=True,slots=True)
class VoiceProviderResult:
    session_id:str;transcripts:tuple[VoiceTranscriptEvent,...]=();audio_chunks:tuple[VoiceAudioChunk,...]=();provider_request_id:str|None=None;final:bool=False
    def __post_init__(self):
        if any(x.session_id!=self.session_id for x in self.transcripts) or any(x.session_id!=self.session_id for x in self.audio_chunks):raise ValueError('voice provider result session mismatch')
    def metadata(self):return {'session_id':self.session_id,'transcript_count':len(self.transcripts),'audio_chunk_count':len(self.audio_chunks),'provider_request_id':self.provider_request_id,'final':self.final,'audio':[x.metadata() for x in self.audio_chunks]}

@dataclass(slots=True)
class VoiceResponse:
    session_id:str;state:str;transcripts:list[dict[str,Any]];audio_chunks:list[VoiceAudioChunk];agent_result:dict[str,Any]|None;provider_result:dict[str,Any];provenance:dict[str,Any]
    def to_dict(self,*,include_audio=False):
        return {'session_id':self.session_id,'state':self.state,'transcripts':self.transcripts,'audio_chunks':[({'audio':bytes(x.audio)}|x.metadata()) if include_audio else x.metadata() for x in self.audio_chunks],'agent_result':self.agent_result,'provider_result':self.provider_result,'provenance':self.provenance}

class VoiceSessionService:
    """Streaming voice interaction layer over the existing PersonalAgent/conversation path."""
    def __init__(self,store,*,model_manager=None,conversation_service=None,provider=None,provider_identity=None,allow_external_sensitive=False):
        self.store=store;self.model_manager=model_manager;self.conversations=conversation_service;self.provider=provider;self.provider_identity=dict(provider_identity or {});self.allow_external_sensitive=bool(allow_external_sensitive);self._providers={}
    def _save(self,s):s.updated_at=now();self.store.save_voice_session(s);return s
    def _load(self,sid,owner=None):
        s=self.store.load_voice_session(sid)
        if owner is not None and s.owner_user_id!=owner:raise PermissionError('voice_session_owner_mismatch')
        return s
    def create(self,*,owner_user_id='user',conversation_session_id=None,classification='PRIVATE',persist_transcript=True):
        if not isinstance(owner_user_id,str) or not owner_user_id.strip():raise ValueError('voice owner required')
        if classification not in VOICE_CLASSIFICATIONS:raise ValueError('invalid voice classification')
        stamp=now();s=VoiceSession(uuid.uuid4().hex,owner_user_id,VoiceSessionState.CREATED.value,stamp,stamp,conversation_session_id,classification,persist_transcript=bool(persist_transcript),provenance={'capability':'voice','raw_audio_persisted':False});return self._save(s)
    def _resolve_provider(self):
        if self.provider is not None:
            ident={'provider':'test-injected','model':'test-injected-voice','capability':'voice','fallback':False}|self.provider_identity
            return self.provider,ident
        if self.model_manager is None:raise RuntimeError('voice_model_manager_unavailable')
        routed=self.model_manager.voice_provider();return routed['adapter'],dict(routed['provenance'])
    def connect(self,session_id,*,owner_user_id='user'):
        s=self._load(session_id,owner_user_id)
        if s.state not in {VoiceSessionState.CREATED.value,VoiceSessionState.UNAVAILABLE.value}:raise ValueError('voice session cannot connect from current state')
        if s.classification in BLOCKED_EXTERNAL_CLASSIFICATIONS and not self.allow_external_sensitive:s.state=VoiceSessionState.UNAVAILABLE.value;s.failure_reason='classification prohibits external voice transmission';self.store.save_voice_event(s.session_id,'voice_blocked',{'reason':s.failure_reason},now());return self._save(s)
        s.state=VoiceSessionState.CONNECTING.value;self._save(s)
        try:provider,prov=self._resolve_provider();ref=provider.open_session({'session_id':s.session_id,'owner_user_id':s.owner_user_id,'classification':s.classification,'input_audio':{'sample_rate':INPUT_RATE,'channels':1,'sample_width':2,'encoding':'pcm_s16le'},'output_audio':{'sample_rate':OUTPUT_RATE,'channels':1,'sample_width':2,'encoding':'pcm_s16le'}})
        except Exception as exc:
            s.state=VoiceSessionState.UNAVAILABLE.value if 'unavailable' in str(exc).lower() or 'external' in str(exc).lower() or 'capability' in str(exc).lower() or 'transport' in str(exc).lower() else VoiceSessionState.FAILED.value;s.failure_reason=type(exc).__name__+':'+str(exc)[:240];self.store.save_voice_event(s.session_id,'voice_connect_failed',{'error_type':type(exc).__name__,'state':s.state},now());return self._save(s)
        if not isinstance(ref,str) or not ref.strip():s.state=VoiceSessionState.FAILED.value;s.failure_reason='provider returned invalid session reference';return self._save(s)
        self._providers[s.session_id]=provider;s.provider_session_reference=ref;s.provider=prov.get('provider');s.model=prov.get('model');s.fallback=bool(prov.get('fallback',False));s.provenance={'capability':'voice','provider':s.provider,'model':s.model,'fallback':s.fallback,'input_modalities':['audio'],'output_modalities':['text','audio'],'raw_audio_persisted':False};s.state=VoiceSessionState.CONNECTED.value;self.store.save_voice_event(s.session_id,'voice_connected',{'provider':s.provider,'model':s.model,'fallback':s.fallback},now());return self._save(s)
    @staticmethod
    def _coerce_result(value,session_id):
        if isinstance(value,VoiceProviderResult):return value
        if not isinstance(value,dict):raise ValueError('malformed voice provider event')
        transcripts=[]
        for raw in value.get('transcripts',[]):
            if not isinstance(raw,dict):raise ValueError('malformed voice transcript event')
            transcripts.append(VoiceTranscriptEvent(str(raw.get('event_id') or uuid.uuid4().hex),session_id,str(raw.get('speaker','')),str(raw.get('text','')),bool(raw.get('final',False)),str(raw.get('timestamp') or now()),raw.get('provider_reference')))
        chunks=[]
        for raw in value.get('audio_chunks',[]):
            if not isinstance(raw,dict) or not isinstance(raw.get('audio'),(bytes,bytearray)):raise ValueError('malformed voice audio event')
            chunks.append(VoiceAudioChunk(session_id,int(raw.get('sequence',len(chunks))),bytes(raw['audio']),str(raw.get('timestamp') or now()),int(raw.get('sample_rate',OUTPUT_RATE)),int(raw.get('channels',1)),int(raw.get('sample_width',2)),str(raw.get('encoding','pcm_s16le')),bool(raw.get('final',False)),raw.get('provider_reference')))
        return VoiceProviderResult(session_id,tuple(transcripts),tuple(chunks),value.get('provider_request_id'),bool(value.get('final',False)))
    def _provider_for(self,s):
        provider=self._providers.get(s.session_id)
        if provider is not None:return provider
        # Streaming sessions are intentionally not resumed across process restarts.
        raise RuntimeError('voice_transport_session_not_resumable_after_restart')
    def push(self,frame:VoiceInputFrame,*,owner_user_id='user'):
        s=self._load(frame.session_id,owner_user_id)
        if s.state not in {VoiceSessionState.CONNECTED.value,VoiceSessionState.ACTIVE.value}:raise ValueError('voice session is not connected')
        provider=self._provider_for(s);s.state=VoiceSessionState.ACTIVE.value;self._save(s);self.store.save_voice_event(s.session_id,'voice_input_frame',frame.metadata(),now())
        try:heard=self._coerce_result(provider.send_audio(s.provider_session_reference,frame),s.session_id)
        except Exception as exc:s.state=VoiceSessionState.FAILED.value;s.failure_reason=type(exc).__name__+':'+str(exc)[:240];self.store.save_voice_event(s.session_id,'voice_provider_failed',{'error_type':type(exc).__name__},now());self._save(s);raise
        # Provider speech before PersonalAgent authorization would bypass SPARKLE policy.
        if heard.audio_chunks:s.state=VoiceSessionState.FAILED.value;s.failure_reason='provider_audio_before_personal_agent_authorization';self._save(s);raise RuntimeError(s.failure_reason)
        transcripts=[x.to_dict() for x in heard.transcripts]
        for x in heard.transcripts:
            self.store.save_voice_event(s.session_id,'voice_transcript',({'speaker':x.speaker,'text':x.text,'final':x.final,'event_id':x.event_id,'provider_reference':x.provider_reference} if s.persist_transcript else {'speaker':x.speaker,'final':x.final,'event_id':x.event_id,'text_persisted':False,'provider_reference':x.provider_reference}),x.timestamp)
        final_user=next((x for x in reversed(heard.transcripts) if x.speaker=='user' and x.final),None)
        if final_user is None:return VoiceResponse(s.session_id,s.state,transcripts,[],None,heard.metadata(),dict(s.provenance))
        if self.conversations is None:s.state=VoiceSessionState.FAILED.value;s.failure_reason='personal_agent_conversation_path_unavailable';self._save(s);raise RuntimeError(s.failure_reason)
        interaction=self.conversations.send(final_user.text,session_id=s.conversation_session_id,device_id='voice:'+s.session_id);s.conversation_session_id=interaction['session_id'];agent_result=interaction['result']
        # Only the verified PersonalAgent response is handed back to the provider for speech rendering.
        try:spoken=self._coerce_result(provider.respond_text(s.provider_session_reference,agent_result['text']),s.session_id)
        except Exception as exc:s.state=VoiceSessionState.FAILED.value;s.failure_reason=type(exc).__name__+':'+str(exc)[:240];self._save(s);raise
        if not spoken.audio_chunks:s.state=VoiceSessionState.FAILED.value;s.failure_reason='voice_provider_returned_no_response_audio';self._save(s);raise RuntimeError(s.failure_reason)
        self.store.save_voice_event(s.session_id,'voice_agent_response',{'goal_id':agent_result.get('goal_id'),'task_run_id':agent_result.get('task_run_id'),'trace_id':agent_result.get('trace_id'),'status':agent_result.get('status'),'provider_request_id':spoken.provider_request_id,'audio_chunks':[x.metadata() for x in spoken.audio_chunks]},now());s.outcome=str(agent_result.get('status'));s.state=VoiceSessionState.ACTIVE.value;self._save(s)
        return VoiceResponse(s.session_id,s.state,transcripts,[*spoken.audio_chunks],agent_result,spoken.metadata(),dict(s.provenance)|{'provider_request_id':spoken.provider_request_id})
    def interrupt(self,session_id,*,owner_user_id='user'):
        s=self._load(session_id,owner_user_id);s.state=VoiceSessionState.STOPPING.value;self._save(s)
        try:provider=self._provider_for(s);result=provider.interrupt(s.provider_session_reference)
        except Exception as exc:result={'interrupted':False,'error_type':type(exc).__name__}
        s.state=VoiceSessionState.CONNECTED.value if result.get('interrupted') else VoiceSessionState.FAILED.value;s.failure_reason=None if result.get('interrupted') else 'provider_interruption_failed';self.store.save_voice_event(s.session_id,'voice_interrupted',{'interrupted':bool(result.get('interrupted'))},now());return self._save(s)
    def cancel(self,session_id,*,owner_user_id='user'):
        s=self._load(session_id,owner_user_id);s.state=VoiceSessionState.STOPPING.value;self._save(s)
        try:self._provider_for(s).close_session(s.provider_session_reference)
        except Exception:pass
        self._providers.pop(s.session_id,None);s.state=VoiceSessionState.CANCELLED.value;s.outcome='CANCELLED';self.store.save_voice_event(s.session_id,'voice_cancelled',{},now());return self._save(s)
    def close(self,session_id,*,owner_user_id='user'):
        s=self._load(session_id,owner_user_id);s.state=VoiceSessionState.STOPPING.value;self._save(s)
        try:self._provider_for(s).close_session(s.provider_session_reference)
        except Exception as exc:s.state=VoiceSessionState.FAILED.value;s.failure_reason=type(exc).__name__;return self._save(s)
        self._providers.pop(s.session_id,None);s.state=VoiceSessionState.COMPLETED.value;s.outcome=s.outcome or 'COMPLETED';self.store.save_voice_event(s.session_id,'voice_completed',{'outcome':s.outcome},now());return self._save(s)
    def inspect(self,session_id,*,owner_user_id='user'):
        s=self._load(session_id,owner_user_id);return {'session':s.to_dict(),'events':self.store.voice_events(session_id)}
    def recover(self,session_id,*,owner_user_id='user'):
        s=self._load(session_id,owner_user_id)
        if s.state in {VoiceSessionState.CONNECTING.value,VoiceSessionState.CONNECTED.value,VoiceSessionState.ACTIVE.value,VoiceSessionState.STOPPING.value}:
            s.state=VoiceSessionState.UNAVAILABLE.value;s.failure_reason='voice_transport_session_not_resumable_after_restart';self.store.save_voice_event(s.session_id,'voice_restart_recovery',{'state':s.state,'reason':s.failure_reason},now());self._save(s)
        return s
    def health(self):
        if self.provider is not None:return {'status':'AVAILABLE','source':'test-injected','live_verified':False}
        if self.model_manager is None:return {'status':'UNAVAILABLE','reason':'voice_model_manager_unavailable','live_verified':False}
        status=self.model_manager.status('voice');return {'status':'HEALTHY' if status['status']=='CONNECTED' else 'UNAVAILABLE','route':status['route'],'live_verified':False,'reason':'actual speech-to-speech inference has not been verified' if status['status']!='CONNECTED' else 'route configured; live session evidence still required'}

# Legacy injected STT/TTS harness retained for backward compatibility with certified lifecycle tests.
class VoiceRuntime:
    def __init__(self,stt=None,tts=None):
        self.stt=stt;self.tts=tts;self.active_turn=None;self._interrupted=set()
    def health(self):return {'stt':'CONNECTED' if self.stt else 'EXTERNALLY_BLOCKED','tts':'CONNECTED' if self.tts else 'EXTERNALLY_BLOCKED','interruption':'SUPPORTED'}
    def begin_turn(self):turn_id=uuid.uuid4().hex;self.active_turn=turn_id;return turn_id
    def interrupt(self,turn_id=None):
        target=turn_id or self.active_turn
        if target:self._interrupted.add(target)
        if target==self.active_turn:self.active_turn=None
        return {'turn_id':target,'interrupted':bool(target)}
    def is_interrupted(self,turn_id):return turn_id in self._interrupted
    def cancel(self,turn_id=None):result=self.interrupt(turn_id);result['cancelled']=result.pop('interrupted');return result
    def resume(self,turn_id=None):
        if turn_id is not None:self._interrupted.discard(turn_id)
        return self.begin_turn()
    def transcribe(self,audio):
        if self.stt is None:raise RuntimeError('external_dependency:stt')
        text=self.stt(audio)
        if not isinstance(text,str) or not text.strip():raise RuntimeError('stt_invalid_result')
        return text
    def speak(self,text,*,turn_id=None):
        if self.tts is None:raise RuntimeError('external_dependency:tts')
        current=turn_id or self.active_turn or self.begin_turn()
        if self.is_interrupted(current):raise RuntimeError('voice_interrupted')
        audio=self.tts(text)
        if self.is_interrupted(current):raise RuntimeError('voice_interrupted')
        if self.active_turn==current:self.active_turn=None
        return audio
