from __future__ import annotations

class SharedInteractionContext:
    def __init__(self,agent,voice,session_service):self.agent=agent;self.voice=voice;self.sessions=session_service
    def text(self,session_id,message):
        session=self.sessions.recover(session_id);result=self.agent.start(message);self.sessions.attach_goal(session_id,result['goal_id']);return result
    def voice_turn(self,session_id,audio):
        text=self.voice.transcribe(audio);result=self.text(session_id,text);spoken=self.voice.speak(result['text']);return {'text':text,'result':result,'audio':spoken}
