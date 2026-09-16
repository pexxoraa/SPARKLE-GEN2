from __future__ import annotations
import os,re,subprocess
from pathlib import Path

class ROS2CommandError(RuntimeError):pass

def ros_environment(setup='/opt/ros/lyrical/setup.bash'):
    p=Path(setup).resolve()
    if not p.is_file() or '/opt/ros/' not in str(p):raise ValueError('invalid_ros_setup')
    c=subprocess.run(['/bin/bash','-c','source "$1" >/dev/null 2>&1; env -0','bash',str(p)],capture_output=True,timeout=8,check=False)
    if c.returncode!=0:raise ROS2CommandError('ros_setup_failed')
    env={}
    for item in c.stdout.split(b'\0'):
        if b'=' in item:
            k,v=item.split(b'=',1);env[k.decode(errors='ignore')]=v.decode(errors='ignore')
    return env

class ROS2CLI:
    def __init__(self,env=None,binary='/opt/ros/lyrical/bin/ros2'):self.env=dict(env or ros_environment());self.binary=str(Path(binary).resolve())
    def run(self,args,timeout=10):
        if not isinstance(args,(list,tuple)) or not args or any(not isinstance(x,str) or len(x)>1000 for x in args):raise ValueError('invalid_ros2_command')
        c=subprocess.run([self.binary,*args],env=self.env,capture_output=True,text=True,timeout=timeout,check=False)
        if c.returncode!=0:raise ROS2CommandError((c.stderr or c.stdout or 'ros2_command_failed').strip()[:300])
        return c.stdout.strip()

class TurtleSimROS2Node:
    def __init__(self,cli=None):self.cli=cli or ROS2CLI()
    def health(self):
        try:nodes=set(self.cli.run(['node','list']).splitlines());return {'ok':'/turtlesim' in nodes,'node':'/turtlesim','simulation':True}
        except Exception as exc:return {'ok':False,'error_type':type(exc).__name__,'simulation':True}
    @staticmethod
    def _parse_pose(text):
        vals={}
        for key in ('x','y','theta'):
            m=re.search(rf'(?m)^{key}:\s*(-?[0-9]+(?:\.[0-9]+)?)',text)
            if not m:raise ROS2CommandError('pose_parse_failed')
            vals[key]=float(m.group(1))
        return vals
    def pose(self):return self._parse_pose(self.cli.run(['topic','echo','/turtle1/pose','--once','--timeout','5'],timeout=8))
    def invoke(self,operation,payload):
        if operation=='status':return {'operation':'status','pose':self.pose(),'simulation':True}
        if operation!='move':raise PermissionError('ros2_live_action_not_supported')
        if set(payload)-{'distance','angle'}:raise ValueError('unsupported_move_fields')
        distance=float(payload.get('distance',0));angle=float(payload.get('angle',0))
        if abs(distance)>1.0 or abs(angle)>1.0:raise ValueError('move_exceeds_transport_bound')
        before=self.pose();request=f'{{linear: {distance:.6f}, angular: {angle:.6f}}}'
        self.cli.run(['service','call','/turtle1/teleport_relative','turtlesim_msgs/srv/TeleportRelative',request],timeout=8)
        after=self.pose();return {'operation':'move','requested':{'distance':distance,'angle':angle},'before':before,'after':after,'simulation':True}
    def verify(self,operation,result):
        if operation=='status':return {'verified':bool(result.get('pose')),'method':'ROS2 pose observation','simulation':True}
        if operation!='move' or result.get('operation')!='move':return {'verified':False,'reason':'operation_mismatch','simulation':True}
        current=self.pose();expected=result.get('after',{});ok=all(abs(current.get(k,999)-float(expected.get(k,0)))<0.05 for k in ('x','y','theta'))
        changed=any(abs(float(result['before'][k])-float(result['after'][k]))>0.01 for k in ('x','y','theta'))
        return {'verified':bool(ok and changed),'method':'independent ROS2 /turtle1/pose reread','pose':current,'simulation':True}

class ROS2ParameterSafetyController:
    def __init__(self,cli=None,node='/sparkle_safety_controller'):self.cli=cli or ROS2CLI();self.node=node
    def health(self):
        try:return {'ok':self.node in set(self.cli.run(['node','list']).splitlines()),'node':self.node}
        except Exception as exc:return {'ok':False,'error_type':type(exc).__name__}
    def _param(self,name):
        text=self.cli.run(['param','get',self.node,name])
        value=text.split(':',1)[-1].strip()
        if value.lower() in {'true','false'}:return value.lower()=='true'
        try:return float(value)
        except ValueError as exc:raise ROS2CommandError('safety_parameter_parse_failed') from exc
    def estop_active(self):return bool(self._param('estop_active'))
    def authorize(self,operation,payload):
        if operation=='status':return True
        if operation!='move' or set(payload)-{'distance','angle'}:return False
        distance=abs(float(payload.get('distance',0)));angle=abs(float(payload.get('angle',0)))
        return distance<=float(self._param('max_distance')) and angle<=float(self._param('max_angle'))
