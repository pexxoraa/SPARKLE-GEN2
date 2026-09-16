from __future__ import annotations

class VoiceRuntime:
    def __init__(self,stt=None,tts=None): self.stt=stt;self.tts=tts
    def health(self):
        return {'stt':'CONNECTED' if self.stt else 'EXTERNALLY_BLOCKED','tts':'CONNECTED' if self.tts else 'EXTERNALLY_BLOCKED'}
    def transcribe(self,audio):
        if self.stt is None: raise RuntimeError('external_dependency:stt')
        text=self.stt(audio)
        if not isinstance(text,str) or not text.strip(): raise RuntimeError('stt_invalid_result')
        return text
    def speak(self,text):
        if self.tts is None: raise RuntimeError('external_dependency:tts')
        return self.tts(text)
