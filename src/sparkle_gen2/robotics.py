from __future__ import annotations

class RobotSafetyGateway:
    def __init__(self,adapter=None,estop=None,verifier=None):self.adapter=adapter;self.estop=estop;self.verifier=verifier
    def health(self):
        if self.adapter is None or self.estop is None:return {'status':'EXTERNALLY_BLOCKED','reason':'robot_adapter_and_independent_estop_required'}
        return {'status':'CONNECTED'}
    def command(self,action,payload,*,approved=False):
        if self.adapter is None or self.estop is None:raise RuntimeError('external_dependency:robot_hardware')
        if self.estop():raise RuntimeError('emergency_stop_active')
        if action!='status' and not approved:raise PermissionError('approval_required')
        if action in {'raw_motor','pwm','direct_joint_voltage'}:raise PermissionError('unsafe_direct_motor_control')
        result=self.adapter(action,dict(payload))
        if not isinstance(result,dict):raise RuntimeError('robot_invalid_observation')
        return result
    def execute_verified(self,action,payload,*,approved=False):
        result=self.command(action,payload,approved=approved)
        if self.verifier is None:raise RuntimeError('external_dependency:robot_verifier')
        evidence=self.verifier(action,result)
        if not isinstance(evidence,dict) or evidence.get('verified') is not True:raise RuntimeError('robot_verification_failed')
        return {'result':result,'verification':evidence}
