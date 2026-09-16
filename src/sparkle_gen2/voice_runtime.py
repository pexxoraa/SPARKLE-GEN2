from __future__ import annotations
import uuid

class VoiceRuntime:
    def __init__(self,stt=None,tts=None):
        self.stt=stt;self.tts=tts;self.active_turn=None;self._interrupted=set()
    def health(self):
        return {'stt':'CONNECTED' if self.stt else 'EXTERNALLY_BLOCKED','tts':'CONNECTED' if self.tts else 'EXTERNALLY_BLOCKED','interruption':'SUPPORTED'}
    def begin_turn(self):
        turn_id=uuid.uuid4().hex;self.active_turn=turn_id;return turn_id
    def interrupt(self,turn_id=None):
        target=turn_id or self.active_turn
        if target:self._interrupted.add(target)
        if target==self.active_turn:self.active_turn=None
        return {'turn_id':target,'interrupted':bool(target)}
    def is_interrupted(self,turn_id):return turn_id in self._interrupted
    def cancel(self,turn_id=None):
        result=self.interrupt(turn_id);result['cancelled']=result.pop('interrupted');return result
    def resume(self,turn_id=None):
        if turn_id is not None:self._interrupted.discard(turn_id)
        return self.begin_turn()
    def transcribe(self,audio):
        if self.stt is None: raise RuntimeError('external_dependency:stt')
        text=self.stt(audio)
        if not isinstance(text,str) or not text.strip(): raise RuntimeError('stt_invalid_result')
        return text
    def speak(self,text,*,turn_id=None):
        if self.tts is None: raise RuntimeError('external_dependency:tts')
        current=turn_id or self.active_turn or self.begin_turn()
        if self.is_interrupted(current):raise RuntimeError('voice_interrupted')
        audio=self.tts(text)
        if self.is_interrupted(current):raise RuntimeError('voice_interrupted')
        if self.active_turn==current:self.active_turn=None
        return audio
