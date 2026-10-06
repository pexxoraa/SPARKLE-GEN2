from __future__ import annotations
import math,time
from dataclasses import dataclass
from datetime import UTC,datetime

@dataclass(frozen=True,slots=True)
class MotionSafetyEnvelope:
    max_velocity:float=0.5
    max_displacement:float=0.5
    max_angle:float=0.5
    max_command_rate_hz:float=5.0
    stale_after_seconds:float=5.0
    workspace:tuple[float,float,float,float]|None=None
    def __post_init__(self):
        if not (0<self.max_velocity<=10 and 0<self.max_displacement<=100 and 0<self.max_angle<=math.pi*2 and 0<self.max_command_rate_hz<=100 and 0<self.stale_after_seconds<=3600):raise ValueError('invalid motion safety limits')
        if self.workspace is not None:
            if len(self.workspace)!=4 or any(not isinstance(x,(int,float)) or isinstance(x,bool) or not math.isfinite(float(x)) for x in self.workspace):raise ValueError('invalid workspace bounds')
            xmin,xmax,ymin,ymax=map(float,self.workspace)
            if not xmin<xmax or not ymin<ymax:raise ValueError('invalid workspace bounds')

class RobotSafetyGateway:
    RAW=frozenset({'raw_motor','pwm','direct_joint_voltage','raw_actuator','raw_joint_command'})
    def __init__(self,adapter=None,estop=None,verifier=None,*,safety:MotionSafetyEnvelope|None=None,state_reader=None,clock=None):
        self.adapter=adapter;self.estop=estop;self.verifier=verifier;self.safety=safety or MotionSafetyEnvelope();self.state_reader=state_reader;self.clock=clock or time.monotonic;self._last_control_at=None
    def health(self):
        if self.adapter is None or self.estop is None:return {'status':'EXTERNALLY_BLOCKED','reason':'robot_adapter_and_independent_estop_required'}
        return {'status':'CONNECTED','safety':{'max_velocity':self.safety.max_velocity,'max_displacement':self.safety.max_displacement,'max_angle':self.safety.max_angle,'max_command_rate_hz':self.safety.max_command_rate_hz,'stale_after_seconds':self.safety.stale_after_seconds,'workspace_limited':self.safety.workspace is not None}}
    @staticmethod
    def _finite(name,value,default=0.0):
        value=default if value is None else value
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(float(value)):raise PermissionError('unsafe_motion_parameter:'+name)
        return float(value)
    @staticmethod
    def _parse_time(value):
        d=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if d.tzinfo is None:d=d.replace(tzinfo=UTC)
        return d.astimezone(UTC)
    def _state(self):
        if self.state_reader is None:return None
        state=self.state_reader()
        if not isinstance(state,dict):raise RuntimeError('robot_state_unavailable')
        stamp=state.get('timestamp') or state.get('observed_at')
        if not stamp:raise RuntimeError('robot_state_timestamp_required')
        age=max(0.0,(datetime.now(UTC)-self._parse_time(stamp)).total_seconds())
        if age>self.safety.stale_after_seconds:raise RuntimeError('stale_robot_state')
        return state
    def _validate_control(self,action,payload):
        if action in self.RAW:raise PermissionError('unsafe_direct_motor_control')
        if action not in {'move','navigate','status'}:raise PermissionError('robot_action_not_allowlisted')
        if action=='status':return
        now_mono=self.clock()
        if self._last_control_at is not None and now_mono-self._last_control_at < 1.0/self.safety.max_command_rate_hz:raise PermissionError('robot_command_rate_exceeded')
        distance=self._finite('distance',payload.get('distance',0.0));angle=self._finite('angle',payload.get('angle',0.0));velocity=self._finite('velocity',payload.get('velocity',min(abs(distance),self.safety.max_velocity)))
        if abs(distance)>self.safety.max_displacement:raise PermissionError('robot_displacement_exceeds_limit')
        if abs(angle)>self.safety.max_angle:raise PermissionError('robot_angle_exceeds_limit')
        if abs(velocity)>self.safety.max_velocity:raise PermissionError('robot_velocity_exceeds_limit')
        state=self._state()
        if self.safety.workspace is not None:
            if state is None:raise RuntimeError('fresh_robot_state_required_for_workspace_check')
            pose=state.get('pose') if isinstance(state.get('pose'),dict) else state
            x=self._finite('state_x',pose.get('x'));y=self._finite('state_y',pose.get('y'))
            target=payload.get('target')
            if isinstance(target,dict):tx=self._finite('target_x',target.get('x'));ty=self._finite('target_y',target.get('y'))
            else:tx=x+distance*math.cos(self._finite('theta',pose.get('theta',0.0)));ty=y+distance*math.sin(self._finite('theta',pose.get('theta',0.0)))
            xmin,xmax,ymin,ymax=self.safety.workspace
            if not (xmin<=tx<=xmax and ymin<=ty<=ymax):raise PermissionError('robot_workspace_boundary_exceeded')
        self._last_control_at=now_mono
    def command(self,action,payload,*,approved=False):
        if self.adapter is None or self.estop is None:raise RuntimeError('external_dependency:robot_hardware')
        if self.estop():raise RuntimeError('emergency_stop_active')
        if action!='status' and not approved:raise PermissionError('approval_required')
        data=dict(payload or {});self._validate_control(action,data);result=self.adapter(action,data)
        if not isinstance(result,dict):raise RuntimeError('robot_invalid_observation')
        return result
    def execute_verified(self,action,payload,*,approved=False):
        result=self.command(action,payload,approved=approved)
        if self.verifier is None:raise RuntimeError('external_dependency:robot_verifier')
        evidence=self.verifier(action,result)
        if not isinstance(evidence,dict) or evidence.get('verified') is not True:raise RuntimeError('robot_verification_failed')
        return {'result':result,'verification':evidence}
