from __future__ import annotations

class AdvancedCodingMode:
    def __init__(self,workflow):self.workflow=workflow
    def inspect(self,path):return self.workflow.inspect_code(path)
    def build(self,name,files,*,approved=False):
        scaffold=self.workflow.scaffold(name,files,approved=approved)
        return {'scaffold':scaffold,'requires_followup_verification':True}

class RoboticsEngineerMode:
    """Bounded engineering workspace over existing robot/world/research services.

    This mode never exposes raw ROS2/shell access. Read projections consume existing services;
    motion remains delegated to RobotSafetyGateway and its independent verification path.
    """
    def __init__(self,robot,world,*,perception=None,experiments=None,documents=None,research=None,engineering=None,max_items=20):
        if not 1<=int(max_items)<=100:raise ValueError('robotics engineer max_items out of range')
        self.robot=robot;self.world=world;self.perception=perception;self.experiments=experiments;self.documents=documents;self.research=research;self.engineering=engineering;self.max_items=int(max_items)
    def inspect(self,robot_id='robot'):
        health=self.robot.health();self.world.observe(robot_id,'robot',health,{'source':'robot_gateway'});return health
    def move(self,action,payload,*,approved=False):
        result=self.robot.command(action,payload,approved=approved);self.world.observe('robot','robot',result,{'source':'robot_gateway_observation'});return result
    def move_verified(self,action,payload,*,approved=False,robot_id='robot'):
        if not approved:raise PermissionError('approval_required')
        execute=getattr(self.robot,'execute_verified',None)
        if not callable(execute):raise RuntimeError('robot_verified_execution_unavailable')
        result=execute(action,payload,approved=True)
        verification=dict(result.get('verification') or {}) if isinstance(result,dict) else {}
        if verification.get('verified') is not True:raise RuntimeError('robot_action_verification_failed')
        observed=result.get('after') or result.get('result') or result
        self.world.observe(robot_id,'robot',dict(observed) if isinstance(observed,dict) else {'result':str(observed)[:500]},{'source':'robot_gateway_verified_action','verification':verification},confidence=1.0)
        return result
    @staticmethod
    def _bounded_mapping(value,limit=20):
        if not isinstance(value,dict):return {}
        out={}
        for i,key in enumerate(sorted(value,key=lambda x:str(x))):
            if i>=limit:break
            v=value[key]
            if isinstance(v,(str,int,float,bool)) or v is None:out[str(key)[:120]]=v if not isinstance(v,str) else v[:1000]
        return out
    def workspace(self,robot_id='robot',*,user_id='user'):
        out={'robot_id':str(robot_id)[:160],'robot':None,'world':None,'perception':None,'experiments':[],'documents':[],'research':{'available':self.research is not None},'engineering':{'available':self.engineering is not None},'limitations':[]}
        try:out['robot']=self.inspect(robot_id)
        except Exception as exc:out['robot']={'status':'UNAVAILABLE','reason':type(exc).__name__}
        node=getattr(self.world,'nodes',{}).get(robot_id)
        if node is not None:
            try:age=self.world.freshness(robot_id)
            except Exception:age=None
            out['world']={'kind':node.kind,'state':self._bounded_mapping(node.state),'epistemic_state':getattr(node,'epistemic_state','observed'),'confidence':getattr(node,'confidence',1.0),'observed_at':node.observed_at,'age_seconds':age,'provenance':self._bounded_mapping(getattr(node,'provenance',{}))}
        if self.perception is not None:
            try:
                current=self.perception.current_state(robot_id);out['perception']={'status':'AVAILABLE','state':current}
            except Exception as exc:out['perception']={'status':'UNAVAILABLE','reason':type(exc).__name__}
        if self.experiments is not None:
            items=list(getattr(self.experiments,'items',{}).values())[:self.max_items]
            out['experiments']=[{'experiment_id':getattr(x,'experiment_id',None),'status':getattr(x,'status',None),'verification_state':getattr(x,'verification_state',None),'project_id':getattr(x,'project_id',None),'research_id':getattr(x,'research_id',None),'updated_at':getattr(x,'updated_at',None)} for x in items]
        if self.documents is not None:
            try:items=self.documents.list(user_id=user_id)[:self.max_items]
            except Exception:items=[]
            out['documents']=[{'document_id':getattr(x,'document_id',None),'filename':str(getattr(x,'filename',''))[:240],'media_type':getattr(x,'media_type',None),'status':getattr(x,'status',None),'classification':getattr(x,'classification',None),'updated_at':getattr(x,'updated_at',None)} for x in items]
        if self.perception is None:out['limitations'].append('perception_service_unavailable')
        if self.experiments is None:out['limitations'].append('experiment_service_unavailable')
        if self.documents is None:out['limitations'].append('document_service_unavailable')
        return out
    def diagnose(self,robot_id='robot',*,user_id='user'):
        state=self.workspace(robot_id,user_id=user_id);findings=[]
        robot=state.get('robot') or {}
        status=str(robot.get('status') or robot.get('state') or '').upper() if isinstance(robot,dict) else ''
        if status in {'EXTERNALLY_BLOCKED','UNAVAILABLE','FAILED','DEGRADED'}:findings.append({'category':'robot_gateway','status':status,'evidence':'robot gateway health'})
        perception=state.get('perception') or {}
        if isinstance(perception,dict) and perception.get('status')=='UNAVAILABLE':findings.append({'category':'perception','status':'UNAVAILABLE','evidence':perception.get('reason')})
        world=state.get('world')
        if world is None:findings.append({'category':'world_state','status':'UNAVAILABLE','evidence':'no robot world-state node'})
        elif world.get('age_seconds') is not None and float(world['age_seconds'])>120:findings.append({'category':'world_state','status':'STALE','evidence':'world-state observation older than 120 seconds'})
        return {'robot_id':state['robot_id'],'status':'ATTENTION' if findings else 'OK','findings':findings[:self.max_items],'workspace':state}
