import unittest
from sparkle_gen2.voice_runtime import VoiceRuntime

class Cycle29Tests(unittest.TestCase):
    def test_voice_interrupt_resume_cancel_lifecycle(self):
        v=VoiceRuntime(lambda b:'text',lambda t:b'audio');first=v.begin_turn();self.assertTrue(v.interrupt(first)['interrupted']);second=v.resume(first);self.assertNotEqual(first,second);self.assertFalse(v.is_interrupted(first));self.assertTrue(v.cancel(second)['cancelled']);self.assertTrue(v.is_interrupted(second))
    def test_resume_creates_new_active_turn(self):
        v=VoiceRuntime(lambda b:'text',lambda t:b'audio');turn=v.resume();self.assertEqual(v.active_turn,turn);self.assertEqual(v.speak('x',turn_id=turn),b'audio');self.assertIsNone(v.active_turn)
if __name__=='__main__':unittest.main()
