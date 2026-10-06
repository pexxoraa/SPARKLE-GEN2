from __future__ import annotations

class SharedInteractionContext:
    def __init__(self,agent,voice,session_service):self.agent=agent;self.voice=voice;self.sessions=session_service
    def text(self,session_id,message):
        session=self.sessions.recover(session_id);result=self.agent.start(message);self.sessions.attach_goal(session_id,result['goal_id']);return result
    def voice_turn(self,session_id,audio):
        turn_id=self.voice.begin_turn();text=self.voice.transcribe(audio);result=self.text(session_id,text);spoken=self.voice.speak(result['text'],turn_id=turn_id);return {'turn_id':turn_id,'text':text,'result':result,'audio':spoken}
    def interrupt_voice(self,turn_id=None):return self.voice.interrupt(turn_id)
    def cancel_voice(self,turn_id=None):return self.voice.cancel(turn_id)
    def resume_voice(self,turn_id=None):return self.voice.resume(turn_id)
