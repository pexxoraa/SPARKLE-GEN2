import tempfile,unittest
from pathlib import Path
from sparkle_gen2.mqtt_adapter import MQTTAdapter
from sparkle_gen2.connector_catalog import build_default_connectors
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.models import ApprovalStatus
from sparkle_gen2.ros2_adapter import ROS2GatewayAdapter
class MQTT:
    def health(self):return {'ok':True,'authenticated':True,'tls':True}
    def read(self,t):return {'topic':t,'value':1}
    def publish(self,t,m):return {'topic':t,'message':m,'published':True}
    def verify(self,o,r):return {'verified':r.get('topic')=='devices/a','method':'broker_reread'}
class Approval:
    status=ApprovalStatus.APPROVED;goal_id='g';task_run_id='t';approval_id='a1'
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
    def test_mqtt_connector_manager_composition_is_owner_device_bound_and_approval_gated(self):
        with tempfile.TemporaryDirectory() as d:
            adapter=MQTTAdapter(MQTT(),allowed_topics={'devices/a'},owner_user_id='alice',device_id='mqtt-device-1')
            m=build_default_connectors(store=Gen2Store(Path(d)/'g.db'),policy=PolicyEngine(),owner_user_id='alice',mqtt_adapter=adapter)
            h=m.health('mqtt',owner_user_id='alice');self.assertEqual(h['status'],'HEALTHY');self.assertEqual(h['authorization_state'],'AUTHORIZED');self.assertTrue(h['configured'])
            r=m.invoke_read('mqtt','read',{'topic':'devices/a'},'mqtt.read',owner_user_id='alice');self.assertEqual(r['status'],'VERIFIED')
            with self.assertRaises(PermissionError):m.invoke('mqtt','publish',{'topic':'devices/a','message':{'on':True}},'mqtt.publish',owner_user_id='alice',goal_id='g',task_run_id='t')
            p=m.invoke('mqtt','publish',{'topic':'devices/a','message':{'on':True}},'mqtt.publish',owner_user_id='alice',goal_id='g',task_run_id='t',approval=Approval());self.assertEqual(p['status'],'VERIFIED')
            with self.assertRaises(PermissionError):m.invoke_read('mqtt','read',{'topic':'devices/a'},'mqtt.read',owner_user_id='bob')
            m.revoke('mqtt',owner_user_id='alice',actor='human');self.assertEqual(m.health('mqtt',owner_user_id='alice')['status'],'REVOKED')
    def test_ros2_gateway_preserves_allowlist_safety_estop_and_verification(self):
        a=ROS2GatewayAdapter(Node(),Safety(),allowed_actions={'status','move'});r=a.invoke('move',{'target':'x'});self.assertTrue(a.verify('move',r)['verified'])
        with self.assertRaises(PermissionError):a.invoke('raw_motor',{})
        with self.assertRaisesRegex(RuntimeError,'emergency_stop'):ROS2GatewayAdapter(Node(),Safety(estop=True)).invoke('move',{})
        with self.assertRaisesRegex(PermissionError,'safety_controller_denied'):ROS2GatewayAdapter(Node(),Safety(allow=False)).invoke('move',{})
if __name__=='__main__':unittest.main()
