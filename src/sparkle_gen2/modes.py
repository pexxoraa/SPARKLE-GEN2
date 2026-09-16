from __future__ import annotations

class AdvancedCodingMode:
    def __init__(self,workflow):self.workflow=workflow
    def inspect(self,path):return self.workflow.inspect_code(path)
    def build(self,name,files,*,approved=False):
        scaffold=self.workflow.scaffold(name,files,approved=approved)
        return {'scaffold':scaffold,'requires_followup_verification':True}

class RoboticsEngineerMode:
    def __init__(self,robot,world):self.robot=robot;self.world=world
    def inspect(self,robot_id='robot'):
        health=self.robot.health();self.world.observe(robot_id,'robot',health,{'source':'robot_gateway'});return health
    def move(self,action,payload,*,approved=False):
        result=self.robot.command(action,payload,approved=approved);self.world.observe('robot','robot',result,{'source':'robot_gateway_observation'});return result
