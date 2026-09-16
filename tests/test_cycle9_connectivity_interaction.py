import unittest
from sparkle_gen2.connector_catalog import Gen1ToolConnector,build_default_connectors
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.notifications import NotificationCenter
from sparkle_gen2.interaction import SharedInteractionContext
from sparkle_gen2.voice_runtime import VoiceRuntime

class G:
    def health(self):return {'tools':['file_read']}
    def invoke(self,t,a):return ToolObservation(True,t,{'path':a.get('path')},{'verified':True})
class Session:
    active_goal_id=None
class Sessions:
    def __init__(self):self.s=Session()
    def recover(self,x):return self.s
    def attach_goal(self,x,g):self.s.active_goal_id=g;return self.s
class Agent:
    def start(self,m):return {'goal_id':'g1','text':'done '+m,'status':'COMPLETED'}

class Cycle9ConnectivityInteractionTests(unittest.TestCase):
    def test_named_connector_catalog_is_explicitly_external(self):
        m=build_default_connectors();names={x['name'] for x in m.discover()};self.assertTrue({'gmail','outlook','calendar','drive','github','browser','mobile','mqtt','ros2'}<=names)
        self.assertEqual(m.health('gmail')['status'],'EXTERNALLY_BLOCKED')
    def test_gen1_tool_connector_preserves_exact_tool_boundary(self):
        c=Gen1ToolConnector(G(),{'read':'file_read'});self.assertTrue(c.health()['ok']);r=c.invoke('read',{'path':'x'});self.assertEqual(r['tool'],'file_read')
        with self.assertRaises(KeyError):c.invoke('shell',{})
    def test_notification_center(self):
        n=NotificationCenter();x=n.create('deadline','Due soon','Project is due','HIGH');self.assertEqual(len(n.list_unread()),1);n.read(x.notification_id);self.assertEqual(n.list_unread(),[])
    def test_voice_and_text_share_session_goal_context(self):
        s=Sessions();ctx=SharedInteractionContext(Agent(),VoiceRuntime(lambda a:'hello',lambda t:b'audio'),s)
        r=ctx.voice_turn('s1',b'x');self.assertEqual(r['text'],'hello');self.assertEqual(s.s.active_goal_id,'g1');self.assertEqual(r['audio'],b'audio')

if __name__=='__main__':unittest.main()
