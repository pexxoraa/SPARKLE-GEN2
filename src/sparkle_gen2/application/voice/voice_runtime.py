from __future__ import annotations
import io,re,uuid,wave
from dataclasses import asdict,dataclass,field
from enum import StrEnum
from typing import Any
from ...core_time import now
from sparkle.model import ModelError

VOICE_CLASSIFICATIONS=frozenset({'PUBLIC','PRIVATE','SENSITIVE','HIGHLY_SENSITIVE','DEVICE_CONTROL'})
BLOCKED_EXTERNAL_CLASSIFICATIONS=frozenset({'SENSITIVE','HIGHLY_SENSITIVE','DEVICE_CONTROL'})
INPUT_RATE=24000
OUTPUT_RATE=24000
MAX_FRAME_BYTES=64000
MAX_TRANSCRIPT_CHARS=16000

class VoiceSessionState(StrEnum):
    CREATED='CREATED';CONNECTING='CONNECTING';CONNECTED='CONNECTED';ACTIVE='ACTIVE';STOPPING='STOPPING';COMPLETED='COMPLETED';FAILED='FAILED';UNAVAILABLE='UNAVAILABLE';CANCELLED='CANCELLED'

@dataclass(slots=True)
class VoiceSession:
    session_id:str;owner_user_id:str;state:str;created_at:str;updated_at:str
    conversation_session_id:str|None=None;classification:str='PRIVATE';provider:str|None=None;model:str|None=None;provider_session_reference:str|None=None;fallback:bool=False;persist_transcript:bool=True;failure_reason:str|None=None;outcome:str|None=None;pending_goal_id:str|None=None;provenance:dict[str,Any]=field(default_factory=dict);last_spoken_text:str=''
    def to_dict(self):return asdict(self)

@dataclass(frozen=True,slots=True)
class VoiceInputFrame:
    session_id:str;sequence:int;audio:bytes;timestamp:str;sample_rate:int=INPUT_RATE;channels:int=1;sample_width:int=2;encoding:str='pcm_s16le';final:bool=False
    def __post_init__(self):
        if not isinstance(self.audio,(bytes,bytearray)) or not self.audio:raise ValueError('voice audio payload required')
        if self.sample_rate!=INPUT_RATE:raise ValueError('voice input sample_rate must be 24000 Hz')
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
        if self.sample_rate!=OUTPUT_RATE:raise ValueError('voice output sample_rate must be 24000 Hz')
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
            s.state=VoiceSessionState.UNAVAILABLE.value if 'unavailable' in str(exc).lower() or 'external' in str(exc).lower() or 'capability' in str(exc).lower() or 'transport' in str(exc).lower() else VoiceSessionState.FAILED.value;s.failure_reason='voice_connect_failed:'+type(exc).__name__;self.store.save_voice_event(s.session_id,'voice_connect_failed',{'error_type':type(exc).__name__,'state':s.state},now());return self._save(s)
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
    @staticmethod
    def _voice_plain_text(text):
        value=str(text or '').replace('\r\n','\n').replace('\r','\n')
        value=value.replace('```','').replace('`','').replace('**','').replace('*','')
        value=value.replace('__','').replace('_','')
        value=value.replace('{','').replace('}','')
        value=re.sub(r'^\s{0,3}#{1,6}\s+','',value,flags=re.MULTILINE)
        value=re.sub(r'^\s{0,3}>\s?','',value,flags=re.MULTILINE)
        value=re.sub(r'^\s*[-+]\s+','',value,flags=re.MULTILINE)
        value=re.sub(r'\[([^]]+)\]\([^)]*\)',r'\1',value)
        value=re.sub(r'\s+',' ',value).strip()
        return value

    @classmethod
    def _voice_digest(cls,text,max_words=115):
        value=cls._voice_plain_text(text)
        words=value.split()
        if len(words)<=max_words:return value
        parts=re.split(r'(?m)(?=\\d+[.)]\\s+)',value)
        parts=[p.strip() for p in parts if p.strip()]
        if len(parts)>=2:
            selected=[]
            for part in parts[:5]:
                pw=part.split()
                if len(pw)>24:part=' '.join(pw[:24])+'…'
                selected.append(part)
                if len(' '.join(selected).split())>=max_words:break
            digest=' '.join(selected)
        else:
            digest=' '.join(words[:max_words])+'…'
        return 'I organized the full answer in the conversation panel. Spoken summary: '+digest

    def _authorized_speech(self,s,provider,agent_result,transcripts,provider_result):
        spoken_text=self._voice_digest(agent_result.get('text',''))
        if not spoken_text:
            raise PermissionError('authorized voice response is empty')
        agent_result=dict(agent_result)
        agent_result['text']=spoken_text
        try:
            spoken=self._coerce_result(provider.respond_text(s.provider_session_reference,spoken_text),s.session_id)
        except Exception as exc:
            recoverable=isinstance(exc,(TimeoutError,ConnectionError,ModelError)) and bool(getattr(exc,'retryable',True))
            if not recoverable:
                s.state=VoiceSessionState.FAILED.value;s.failure_reason='voice_tts_failed:'+type(exc).__name__;self._save(s);raise (ValueError if isinstance(exc,ValueError) else PermissionError if isinstance(exc,PermissionError) else RuntimeError)(s.failure_reason) from None
            # The action/conversation has already been authorized by SPARKLE at
            # this point. Never turn a transient speech-generation failure into
            # an app 500 or ask the user to repeat a command that may already have run.
            reason=type(exc).__name__
            s.failure_reason='voice_tts_failed:'+reason
            s.state=VoiceSessionState.ACTIVE.value
            fallback=dict(agent_result)
            fallback['voice_tts_fallback']=True
            if fallback.get('voice_answer_request'):
                fallback['text']='I had trouble generating the spoken answer. The conversation has been preserved; you can continue here.'
            elif not fallback.get('text'):
                fallback['text']='The request was processed, but I could not generate the spoken response.'
            s.last_spoken_text=str(fallback.get('text') or '').strip()
            self._save(s)
            self.store.save_voice_event(s.session_id,'voice_tts_failed',{'error_type':reason,'fallback':True},now())
            return VoiceResponse(s.session_id,s.state,transcripts,[],fallback,provider_result,dict(s.provenance)|{'voice_tts_fallback':True})
        if not spoken.audio_chunks:
            fallback=dict(agent_result)|{'voice_tts_fallback':True}
            if fallback.get('voice_answer_request'):
                fallback['text']='I could not generate the spoken answer, but the conversation is still active.'
            else:
                fallback['text']=str(fallback.get('text') or 'The request was processed, but there was no spoken response.')
            s.last_spoken_text=str(fallback.get('text') or '').strip()
            s.state=VoiceSessionState.ACTIVE.value;s.failure_reason='voice_provider_returned_no_response_audio';self._save(s)
            self.store.save_voice_event(s.session_id,'voice_tts_failed',{'error_type':'no_audio','fallback':True},now())
            return VoiceResponse(s.session_id,s.state,transcripts,[],fallback,provider_result,dict(s.provenance)|{'voice_tts_fallback':True})
        assistant=[x.to_dict() for x in spoken.transcripts]
        assistant_text=' '.join(str(x.text).strip() for x in spoken.transcripts if x.speaker=='assistant' and x.text).strip()
        if assistant_text:s.last_spoken_text=assistant_text
        for x in spoken.transcripts:
            self.store.save_voice_event(s.session_id,'voice_transcript',({'speaker':x.speaker,'text':x.text,'final':x.final,'event_id':x.event_id,'provider_reference':x.provider_reference} if s.persist_transcript else {'speaker':x.speaker,'final':x.final,'event_id':x.event_id,'text_persisted':False,'provider_reference':x.provider_reference}),x.timestamp)
        if agent_result.get('voice_answer_request') and self.conversations is not None:
            if assistant_text:
                self.conversations.record_assistant(assistant_text,session_id=s.conversation_session_id,metadata={'source':'voice_live_authorized_answer'})
        self.store.save_voice_event(s.session_id,'voice_agent_response',{'goal_id':agent_result.get('goal_id'),'task_run_id':agent_result.get('task_run_id'),'trace_id':agent_result.get('trace_id'),'status':agent_result.get('status'),'provider_request_id':spoken.provider_request_id,'audio_chunks':[x.metadata() for x in spoken.audio_chunks]},now())
        s.pending_goal_id=None;s.outcome=str(agent_result.get('status'));s.state=VoiceSessionState.ACTIVE.value;self._save(s)
        return VoiceResponse(s.session_id,s.state,[*transcripts,*assistant],[*spoken.audio_chunks],agent_result,spoken.metadata()|{'input_provider_result':provider_result},dict(s.provenance)|{'provider_request_id':spoken.provider_request_id})
    @staticmethod
    def _is_incomplete_utterance(text):
        normalized=' '.join(str(text or '').lower().strip().split()).rstrip('.,!?;:')
        if not normalized:return True
        safe_commands={'stop','cancel','pause','resume','continue','retry','run','execute','approve','reject','yes','no'}
        greetings={'hi','hello','hey','thanks','thank you','good morning','good afternoon','good evening','hi sparkle','hello sparkle','hey sparkle'}
        if normalized in safe_commands or normalized in greetings:return False
        incomplete={'what','why','how','when','where','who','can','could','would','please','tell me','what is','what are','how do','how does','why is','why are','can you','could you','tell me about'}
        return normalized in incomplete

    @staticmethod
    def _normalize_voice_text(text):
        return ' '.join(str(text or '').lower().strip().split()).strip(' \t\r\n.,!?;:…')

    @classmethod
    def _is_playback_echo(cls,spoken,text):
        heard=cls._normalize_voice_text(text)
        previous=cls._normalize_voice_text(spoken)
        if not heard or not previous:return False
        if heard==previous or heard.startswith(previous+' ') or previous.startswith(heard+' '):return True
        heard_words=heard.split();previous_words=previous.split()
        if len(heard_words)<2 or len(previous_words)<2:return False
        overlap=sum(1 for a,b in zip(heard_words,previous_words) if a==b)
        return overlap>=min(5,len(heard_words),len(previous_words)) and overlap/max(1,min(len(heard_words),len(previous_words)))>=0.8

    def push(self,frame:VoiceInputFrame,*,owner_user_id='user'):
        s=self._load(frame.session_id,owner_user_id)
        if s.state not in {VoiceSessionState.CONNECTED.value,VoiceSessionState.ACTIVE.value}:raise ValueError('voice session is not connected')
        if s.pending_goal_id:raise RuntimeError('voice_session_waiting_for_authorization')
        provider=self._provider_for(s);s.state=VoiceSessionState.ACTIVE.value;self._save(s);self.store.save_voice_event(s.session_id,'voice_input_frame',frame.metadata(),now())
        try:
            heard=self._coerce_result(provider.send_audio(s.provider_session_reference,frame),s.session_id)
        except Exception as exc:
            recoverable=isinstance(exc,(TimeoutError,ConnectionError,ModelError)) and bool(getattr(exc,'retryable',True))
            if not recoverable:
                s.state=VoiceSessionState.FAILED.value;s.failure_reason='voice_input_failed:'+type(exc).__name__;self.store.save_voice_event(s.session_id,'voice_provider_failed',{'error_type':type(exc).__name__,'recoverable':False},now());self._save(s);raise (ValueError if isinstance(exc,ValueError) else PermissionError if isinstance(exc,PermissionError) else RuntimeError)(s.failure_reason) from None
            reason=type(exc).__name__
            s.state=VoiceSessionState.CONNECTED.value
            s.failure_reason='voice_input_failed:'+reason
            self.store.save_voice_event(s.session_id,'voice_provider_failed',{'error_type':reason,'recoverable':True},now());self._save(s)
            fallback={'text':'I had trouble hearing that. Please say it again.','status':'FAILED','voice_retry':True,'provenance':{'capability':'voice_recovery'}}
            return VoiceResponse(s.session_id,s.state,[],[],fallback,{'final':False,'recoverable':True,'provider_error':reason},dict(s.provenance)|{'voice_recovery':True})
        # Provider speech before PersonalAgent authorization would bypass SPARKLE policy.
        if heard.audio_chunks:s.state=VoiceSessionState.FAILED.value;s.failure_reason='provider_audio_before_personal_agent_authorization';self._save(s);raise RuntimeError(s.failure_reason)
        transcripts=[x.to_dict() for x in heard.transcripts]
        for x in heard.transcripts:
            self.store.save_voice_event(s.session_id,'voice_transcript',({'speaker':x.speaker,'text':x.text,'final':x.final,'event_id':x.event_id,'provider_reference':x.provider_reference} if s.persist_transcript else {'speaker':x.speaker,'final':x.final,'event_id':x.event_id,'text_persisted':False,'provider_reference':x.provider_reference}),x.timestamp)
        final_user=next((x for x in reversed(heard.transcripts) if x.speaker=='user' and x.final),None)
        if final_user is None:return VoiceResponse(s.session_id,s.state,transcripts,[],None,heard.metadata(),dict(s.provenance))
        if self._is_playback_echo(s.last_spoken_text,final_user.text):
            self.store.save_voice_event(s.session_id,'voice_echo_suppressed',{'reason':'matches_last_authorized_spoken_text','speaker':'user'},now())
            return VoiceResponse(s.session_id,s.state,transcripts,[],None,heard.metadata()|{'echo_suppressed':True},dict(s.provenance)|{'echo_suppressed':True})
        if self.conversations is None:s.state=VoiceSessionState.FAILED.value;s.failure_reason='personal_agent_conversation_path_unavailable';self._save(s);raise RuntimeError(s.failure_reason)
        if self._is_incomplete_utterance(final_user.text):
            interaction=self.conversations.record_external(final_user.text,'I only caught part of that. Please repeat the question or command.',session_id=s.conversation_session_id,device_id='voice:'+s.session_id)
            s.conversation_session_id=interaction['session_id']
            agent_result={'text':'I only caught part of that. Please repeat the question or command.','status':'COMPLETED','voice_clarification':True,'provenance':{'capability':'voice_clarification'}}
        elif getattr(self.conversations,'_looks_like_knowledge_question',lambda _text:False)(final_user.text):
            interaction=self.conversations.record_user(final_user.text,session_id=s.conversation_session_id,device_id='voice:'+s.session_id,metadata={'source':'voice_live'})
            s.conversation_session_id=interaction['session_id']
            agent_result={'text':'ANSWER_REQUEST: '+final_user.text,'status':'COMPLETED','voice_answer_request':True,'provenance':{'capability':'voice_answer','authorization':'sparkle_core'}}
        else:
            try:
                interaction=self.conversations.send(final_user.text,session_id=s.conversation_session_id,device_id='voice:'+s.session_id)
                s.conversation_session_id=interaction['session_id'];agent_result=interaction['result']
            except Exception as exc:
                reason=type(exc).__name__
                s.state=VoiceSessionState.ACTIVE.value;s.failure_reason='voice_agent_failed:'+reason
                self.store.save_voice_event(s.session_id,'voice_agent_failed',{'error_type':reason,'recoverable':True},now());self._save(s)
                return VoiceResponse(s.session_id,s.state,transcripts,[],{'text':'I hit a temporary processing issue. I did not retry the request automatically; check your latest task/result before repeating it.','status':'FAILED','voice_retry':True,'provenance':{'capability':'voice_recovery','reason':'agent_dispatch_failed'}},{'final':False,'recoverable':True,'provider_error':reason},dict(s.provenance)|{'voice_recovery':True})
        if agent_result.get('status')=='WAITING':
            s.pending_goal_id=str(agent_result.get('goal_id') or '');s.outcome='WAITING';self.store.save_voice_event(s.session_id,'voice_agent_waiting',{'goal_id':s.pending_goal_id,'task_run_id':agent_result.get('task_run_id'),'trace_id':agent_result.get('trace_id'),'approval_count':len(agent_result.get('approvals',[]))},now());self._save(s)
            return VoiceResponse(s.session_id,s.state,transcripts,[],agent_result,heard.metadata()|{'authorization_pending':True},dict(s.provenance))
        return self._authorized_speech(s,provider,agent_result,transcripts,heard.metadata())
    def complete_pending(self,session_id,*,owner_user_id='user',agent_result=None):
        s=self._load(session_id,owner_user_id)
        if not s.pending_goal_id:raise ValueError('voice_session_has_no_pending_goal')
        provider=self._provider_for(s)
        if agent_result is None:
            if self.conversations is None:raise RuntimeError('personal_agent_conversation_path_unavailable')
            agent_result=self.conversations.agent.resume(s.pending_goal_id)
        if str(agent_result.get('goal_id') or '')!=s.pending_goal_id:raise PermissionError('voice_pending_goal_mismatch')
        if agent_result.get('status')=='WAITING':
            self._save(s);return VoiceResponse(s.session_id,s.state,[],[],agent_result,{'authorization_pending':True},dict(s.provenance))
        validate=getattr(provider,'validate_pending_call',None)
        if callable(validate):validate(s.provider_session_reference)
        return self._authorized_speech(s,provider,agent_result,[],{'pending_resumed':True})
    def resume_pending(self,session_id,*,owner_user_id='user'):
        return self.complete_pending(session_id,owner_user_id=owner_user_id)
    def interrupt(self,session_id,*,owner_user_id='user'):
        s=self._load(session_id,owner_user_id);s.state=VoiceSessionState.STOPPING.value;self._save(s)
        try:
            provider=self._provider_for(s)
            mark=getattr(provider,'mark_user_interrupt',None)
            if callable(mark):mark(s.provider_session_reference)
            result=provider.interrupt(s.provider_session_reference)
        except Exception as exc:result={'interrupted':False,'error_type':type(exc).__name__}
        s.state=VoiceSessionState.CONNECTED.value if result.get('interrupted') else VoiceSessionState.FAILED.value;s.failure_reason=None if result.get('interrupted') else 'provider_interruption_failed';s.pending_goal_id=None if result.get('interrupted') else s.pending_goal_id
        if result.get('interrupted'):
            s.provenance=dict(s.provenance)|{'authorization_reset':True}
        self.store.save_voice_event(s.session_id,'voice_interrupted',{'interrupted':bool(result.get('interrupted'))},now());return self._save(s)
    def cancel(self,session_id,*,owner_user_id='user'):
        s=self._load(session_id,owner_user_id);s.state=VoiceSessionState.STOPPING.value;self._save(s)
        try:self._provider_for(s).close_session(s.provider_session_reference)
        except Exception:pass
        self._providers.pop(s.session_id,None);s.pending_goal_id=None;s.state=VoiceSessionState.CANCELLED.value;s.outcome='CANCELLED';self.store.save_voice_event(s.session_id,'voice_cancelled',{},now());return self._save(s)
    def close(self,session_id,*,owner_user_id='user'):
        s=self._load(session_id,owner_user_id);s.state=VoiceSessionState.STOPPING.value;self._save(s)
        try:self._provider_for(s).close_session(s.provider_session_reference)
        except Exception as exc:s.state=VoiceSessionState.FAILED.value;s.failure_reason=type(exc).__name__;return self._save(s)
        self._providers.pop(s.session_id,None);s.pending_goal_id=None;s.state=VoiceSessionState.COMPLETED.value;s.outcome=s.outcome or 'COMPLETED';self.store.save_voice_event(s.session_id,'voice_completed',{'outcome':s.outcome},now());return self._save(s)
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
        status=self.model_manager.status('voice');live=status['status']=='CONNECTED';return {'status':'HEALTHY' if live else 'UNAVAILABLE','route':status['route'],'live_verified':live,'reason':'configured voice provider is not live accepted' if not live else 'configured voice provider is live accepted and authorization-gated'}

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
