from __future__ import annotations
import json
from pathlib import Path
from .gen1 import ToolObservation
from .ros2_adapter import ROS2GatewayAdapter
from .ros2_live import ROS2ParameterSafetyController,TurtleSimROS2Node

ROS2_STATUS_DEF={'name':'ros2_sim_status','description':'Read the current approved ROS2 simulation pose/status. This is read-only simulation state, never physical robot control.','parameters':{'type':'object','properties':{},'additionalProperties':False}}
ROS2_MOVE_DEF={'name':'ros2_sim_move','description':'Move the approved ROS2 simulation by bounded relative distance and angle. Requires human approval and independent safety-controller authorization and pose verification. Simulation only; never direct motor control.','parameters':{'type':'object','properties':{'distance':{'type':'number','minimum':-0.5,'maximum':0.5},'angle':{'type':'number','minimum':-0.5,'maximum':0.5}},'required':['distance','angle'],'additionalProperties':False}}

class EnvironmentGateway:
    """Adds typed Gen-2 environment tools while delegating all Gen-1 behavior unchanged."""
    def __init__(self,base,*,ros2=None):self.base=base;self.ros2=ros2
    def retrieve_context(self,*a,**k):return self.base.retrieve_context(*a,**k)
    def plan(self,*a,**k):return self.base.plan(*a,**k)
    def approval_status(self,*a,**k):return self.base.approval_status(*a,**k)
    def health(self):
        value=dict(self.base.health());tools=list(value.get('tools',[]));defs=list(value.get('tool_definitions',[]));environment={}
        if self.ros2 is not None:
            h=self.ros2.health();environment['ros2_simulation']=h
            if h.get('ok'):
                tools.extend(['ros2_sim_status','ros2_sim_move']);defs.extend([ROS2_STATUS_DEF,ROS2_MOVE_DEF])
        value['tools']=sorted(set(tools));value['tool_definitions']=defs;value['environment']=environment;return value
    def artifacts(self,*a,**k):return self.base.artifacts(*a,**k)
    def artifact_content(self,*a,**k):return self.base.artifact_content(*a,**k)
    def invoke(self,tool,arguments):
        if tool not in {'ros2_sim_status','ros2_sim_move'}:return self.base.invoke(tool,arguments)
        if self.ros2 is None or not self.ros2.health().get('ok'):return ToolObservation(False,tool,{'error':'ROS2 simulation unavailable','error_type':'ExternalDependency'},{'verified':False,'reason':'ros2_simulation_unavailable'})
        try:
            if tool=='ros2_sim_status':
                if arguments:raise ValueError('ros2_sim_status_accepts_no_arguments')
                result=self.ros2.invoke('status',{})
                verification=self.ros2.verify('status',result)
            else:
                if set(arguments)!={'distance','angle'}:raise ValueError('ros2_sim_move_requires_distance_and_angle')
                result=self.ros2.invoke('move',{'distance':float(arguments['distance']),'angle':float(arguments['angle'])})
                verification=self.ros2.verify('move',result)
            return ToolObservation(True,tool,result,verification)
        except Exception as exc:return ToolObservation(False,tool,{'error':str(exc)[:200],'error_type':type(exc).__name__},{'verified':False,'reason':'environment_execution_failed'})

def load_environment_gateway(base,path):
    p=Path(path)
    if not p.exists():return base
    data=json.loads(p.read_text())
    if not isinstance(data,dict) or set(data)-{'ros2_simulation'}:raise ValueError('invalid_environment_gateway_config')
    ros2=None
    if data.get('ros2_simulation') is True:ros2=ROS2GatewayAdapter(TurtleSimROS2Node(),ROS2ParameterSafetyController(),allowed_actions={'status','move'})
    return EnvironmentGateway(base,ros2=ros2)
