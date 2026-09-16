import unittest
from sparkle_gen2.mqtt_adapter import MQTTAdapter
from sparkle_gen2.ros2_adapter import ROS2GatewayAdapter
class MQTT:
    def health(self):return {'ok':True}
    def read(self,t):return {'topic':t,'value':1}
    def publish(self,t,m):return {'topic':t,'message':m,'published':True}
    def verify(self,o,r):return {'verified':r.get('topic')=='devices/a','method':'broker_reread'}
class Node:
    def health(self):return {'ok':True}
    def invoke(self,o,p):return {'operation':o,'pose':'p1'}
    def verify(self,o,r):return {'verified':r.get('operation')==o,'method':'ros_state'}
class Safety:
    def __init__(self,estop=False,allow=True):self.estop=estop;self.allow=allow
    def health(self):return {'ok':True}
    def estop_active(self):return self.estop
    def authorize(self,o,p):return self.allow
class Cycle33Tests(unittest.TestCase):
    def test_mqtt_topic_allowlist_publish_read_and_verify(self):
        a=MQTTAdapter(MQTT(),allowed_topics={'devices/a'});self.assertTrue(a.health()['ok']);r=a.invoke('publish',{'topic':'devices/a','message':{'on':True}});self.assertTrue(a.verify('publish',r)['verified'])
        with self.assertRaises(PermissionError):a.invoke('publish',{'topic':'other','message':1})
    def test_mqtt_fails_closed_without_broker(self):
        with self.assertRaisesRegex(RuntimeError,'mqtt'):MQTTAdapter(allowed_topics={'x'}).invoke('read',{'topic':'x'})
    def test_ros2_gateway_preserves_allowlist_safety_estop_and_verification(self):
        a=ROS2GatewayAdapter(Node(),Safety(),allowed_actions={'status','move'});r=a.invoke('move',{'target':'x'});self.assertTrue(a.verify('move',r)['verified'])
        with self.assertRaises(PermissionError):a.invoke('raw_motor',{})
        with self.assertRaisesRegex(RuntimeError,'emergency_stop'):ROS2GatewayAdapter(Node(),Safety(estop=True)).invoke('move',{})
        with self.assertRaisesRegex(PermissionError,'safety_controller_denied'):ROS2GatewayAdapter(Node(),Safety(allow=False)).invoke('move',{})
if __name__=='__main__':unittest.main()
