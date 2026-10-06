from __future__ import annotations

class ROS2GatewayAdapter:
    RAW={'raw_motor','pwm','direct_joint_voltage','raw_joint_command'}
    def __init__(self,node=None,safety=None,*,allowed_actions=None):self.node=node;self.safety=safety;self.allowed_actions=set(allowed_actions or {'status','move'})
    def health(self):
        if self.node is None or self.safety is None:return {'ok':False,'status':'EXTERNALLY_BLOCKED','dependency':'ROS2 node + independent safety controller'}
        return {'ok':bool(self.node.health().get('ok')) and bool(self.safety.health().get('ok')),'status':'CONNECTED'}
    def invoke(self,operation,payload):
        if self.node is None or self.safety is None:raise RuntimeError('external_dependency:ros2')
        if operation in self.RAW:raise PermissionError('unsafe_direct_motor_control')
        if operation not in self.allowed_actions:raise PermissionError('ros2_action_not_allowlisted')
        if self.safety.estop_active():raise RuntimeError('emergency_stop_active')
        if not self.safety.authorize(operation,dict(payload)):raise PermissionError('safety_controller_denied')
        result=self.node.invoke(operation,dict(payload))
        if not isinstance(result,dict):raise RuntimeError('ros2_invalid_observation')
        return result
    def verify(self,operation,result):
        if self.node is None:return {'verified':False,'reason':'ros2_not_connected'}
        v=self.node.verify(operation,result);return v if isinstance(v,dict) and v.get('verified') is True else {'verified':False,'reason':'verification_failed'}
