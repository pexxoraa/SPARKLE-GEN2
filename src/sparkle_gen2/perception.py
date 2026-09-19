from __future__ import annotations
import hashlib,json
from dataclasses import asdict,dataclass,field
from datetime import UTC,datetime
from typing import Any

SENSOR_TYPES=frozenset({'camera','lidar','depth','imu','odometry','gps','joint_state','pose','battery','proximity'})
FRESHNESS_STATES=frozenset({'FRESH','STALE','EXPIRED'})


def _iso(v):
    d=datetime.fromisoformat(str(v).replace('Z','+00:00'))
    if d.tzinfo is None:raise ValueError('observation timestamp must be timezone-aware')
    return d.astimezone(UTC)

def _canon(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False)

@dataclass(slots=True)
class PerceptionObservation:
    observation_id:str
    device_id:str
    robot_id:str
    sensor_type:str
    timestamp:str
    frame:str
    observation_type:str
    data:dict[str,Any]
    confidence:float
    source:dict[str,Any]
    provenance:dict[str,Any]
    verified:bool=False
    created_at:str|None=None
    def to_dict(self):return asdict(self)

@dataclass(slots=True)
class FusionResult:
    robot_id:str
    status:str
    observation_ids:list[str]
    state:dict[str,Any]
    conflicts:list[dict[str,Any]]=field(default_factory=list)
    provenance:list[dict[str,Any]]=field(default_factory=list)
    def to_dict(self):return asdict(self)

class ROS2PosePerceptionAdapter:
    def __init__(self,gateway,*,robot_id='turtle1',device_id='ros2-sim',frame='turtlesim/world'):
        self.gateway=gateway;self.robot_id=robot_id;self.device_id=device_id;self.frame=frame
    def health(self):
        h=self.gateway.health() if self.gateway is not None else {'ok':False,'status':'EXTERNALLY_BLOCKED'}
        return {'status':'CONNECTED' if h.get('ok') else 'UNAVAILABLE','simulation':True,'detail':h}
    def observe(self):
        if self.gateway is None or not self.gateway.health().get('ok'):raise RuntimeError('perception_source_unavailable')
        result=self.gateway.invoke('status',{})
        pose=result.get('pose') if isinstance(result,dict) else None
        if not isinstance(pose,dict) or set(pose)!={'x','y','theta'}:raise RuntimeError('malformed_ros2_pose_observation')
        return {'device_id':self.device_id,'robot_id':self.robot_id,'sensor_type':'pose','timestamp':datetime.now(UTC).isoformat(),'frame':self.frame,'observation_type':'pose','data':{'x':float(pose['x']),'y':float(pose['y']),'theta':float(pose['theta'])},'confidence':1.0,'source':{'kind':'simulation','adapter':'ros2','topic':'/turtle1/pose'},'provenance':{'simulation':True,'transport':'ROS2 /turtle1/pose'}}

class PerceptionService:
    def __init__(self,store,world,*,model_manager=None,fresh_seconds=10.0,expire_seconds=120.0,pose_conflict_tolerance=0.25):
        self.store=store;self.world=world;self.model_manager=model_manager;self.fresh_seconds=float(fresh_seconds);self.expire_seconds=float(expire_seconds);self.pose_conflict_tolerance=float(pose_conflict_tolerance);self.robots={};self.sources={}
        if not 0<self.fresh_seconds<self.expire_seconds:raise ValueError('invalid freshness thresholds')
    def register_robot(self,robot_id,*,device_id,source=None,capabilities=None):
        if not robot_id or not device_id:raise ValueError('robot and device identity required')
        if robot_id in self.robots:raise ValueError('duplicate robot identity')
        self.robots[robot_id]={'robot_id':robot_id,'device_id':device_id,'capabilities':sorted(set(capabilities or []))}
        if source is not None:self.sources[robot_id]=source
        return dict(self.robots[robot_id])
    @staticmethod
    def observation_id(payload):
        identity={k:payload[k] for k in ('device_id','robot_id','sensor_type','timestamp','frame','observation_type','data','source')}
        return 'obs_'+hashlib.sha256(_canon(identity).encode()).hexdigest()[:32]
    def normalize(self,payload,*,verified=False):
        if not isinstance(payload,dict):raise ValueError('perception payload must be an object')
        required={'device_id','robot_id','sensor_type','timestamp','frame','observation_type','data','confidence','source','provenance'}
        if set(payload)!=required:raise ValueError('perception payload fields are invalid')
        robot_id=str(payload['robot_id']);device_id=str(payload['device_id'])
        if robot_id not in self.robots:raise KeyError('unknown robot identity')
        if self.robots[robot_id]['device_id']!=device_id:raise ValueError('robot/device identity mismatch')
        sensor=str(payload['sensor_type'])
        if sensor not in SENSOR_TYPES:raise ValueError('unsupported sensor type')
        _iso(payload['timestamp'])
        confidence=float(payload['confidence'])
        if not 0.0<=confidence<=1.0:raise ValueError('confidence out of range')
        if not isinstance(payload['data'],dict) or not isinstance(payload['source'],dict) or not payload['source']:raise ValueError('perception data/source invalid')
        oid=self.observation_id(payload)
        return PerceptionObservation(oid,device_id,robot_id,sensor,str(payload['timestamp']),str(payload['frame']),str(payload['observation_type']),dict(payload['data']),confidence,dict(payload['source']),dict(payload['provenance']),bool(verified),datetime.now(UTC).isoformat())
    def freshness(self,observation,*,at=None):
        o=observation if isinstance(observation,PerceptionObservation) else PerceptionObservation(**observation)
        instant=at or datetime.now(UTC);instant=instant if instant.tzinfo else instant.replace(tzinfo=UTC);age=max(0.0,(instant-_iso(o.timestamp)).total_seconds())
        state='FRESH' if age<=self.fresh_seconds else ('STALE' if age<=self.expire_seconds else 'EXPIRED')
        return {'state':state,'age_seconds':age,'observed_at':o.timestamp}
    def process(self,payload,*,verified=False):
        obs=self.normalize(payload,verified=verified)
        existing=None
        try:existing=self.store.load_perception_observation(obs.observation_id)
        except KeyError:pass
        if existing is None:self.store.save_perception_observation(obs)
        else:obs=existing
        fused=self.fuse(obs.robot_id)
        if fused.status=='CURRENT':self._update_world(obs.robot_id,fused)
        return {'observation':obs.to_dict(),'freshness':self.freshness(obs),'fusion':fused.to_dict(),'world_updated':fused.status=='CURRENT'}
    def observe(self,robot_id):
        if robot_id not in self.robots:raise KeyError('unknown robot identity')
        source=self.sources.get(robot_id)
        if source is None:return {'status':'UNAVAILABLE','robot_id':robot_id,'reason':'perception source not connected'}
        try:payload=source.observe()
        except Exception as exc:return {'status':'UNAVAILABLE','robot_id':robot_id,'reason':type(exc).__name__}
        result=self.process(payload,verified=True);return {'status':'OBSERVED',**result}
    def observations(self,robot_id=None):
        rows=self.store.perception_observations(robot_id=robot_id);return [PerceptionObservation(**x) if isinstance(x,dict) else x for x in rows]
    @staticmethod
    def _pose_conflict(a,b,tol):return any(abs(float(a.get(k,0))-float(b.get(k,0)))>tol for k in ('x','y','theta'))
    def fuse(self,robot_id,*,at=None):
        if robot_id not in self.robots:raise KeyError('unknown robot identity')
        rows=self.observations(robot_id);fresh=[]
        for o in rows:
            f=self.freshness(o,at=at)
            if f['state']=='FRESH':fresh.append((o,f))
        if not fresh:return FusionResult(robot_id,'STALE_OR_UNAVAILABLE',[],{},[],[])
        latest={};conflicts=[]
        for o,f in sorted(fresh,key=lambda x:_iso(x[0].timestamp)):
            key=o.observation_type;prior=latest.get(key)
            same_source=prior is not None and prior.device_id==o.device_id and prior.source==o.source
            if prior is not None and not same_source and key=='pose' and self._pose_conflict(prior.data,o.data,self.pose_conflict_tolerance):
                conflicts.append({'observation_type':'pose','a':prior.observation_id,'b':o.observation_id})
            if prior is None or same_source or _iso(o.timestamp)>=_iso(prior.timestamp):latest[key]=o
        if conflicts:return FusionResult(robot_id,'CONFLICT',[o.observation_id for o,_ in fresh],{},conflicts,[o.provenance for o,_ in fresh])
        state={};ids=[];prov=[]
        for key,o in latest.items():state[key]=dict(o.data);ids.append(o.observation_id);prov.append({'observation_id':o.observation_id,'source':o.source,'confidence':o.confidence,'verified':o.verified,'timestamp':o.timestamp})
        return FusionResult(robot_id,'CURRENT',ids,state,[],prov)
    def _update_world(self,robot_id,fused):
        latest=max((self.store.load_perception_observation(x) for x in fused.observation_ids),key=lambda o:_iso(o.timestamp));current=self.world.nodes.get(robot_id)
        if current is not None:
            old=current.provenance.get('observation_timestamp')
            if old and _iso(old)>_iso(latest.timestamp):return current
        state=dict(current.state) if current is not None else {}
        state.update(fused.state);state['last_observation']=latest.observation_id;state['last_seen']=latest.timestamp;state['observation_freshness']='FRESH';state['confidence']={p['observation_id']:p['confidence'] for p in fused.provenance};state.setdefault('safety_state','UNKNOWN')
        prov={'source':'perception','observation_ids':list(fused.observation_ids),'observation_id':latest.observation_id,'observation_timestamp':latest.timestamp,'device_id':latest.device_id,'sensor_type':latest.sensor_type,'simulation':bool(latest.source.get('kind')=='simulation')}
        return self.world.observe(robot_id,'robot',state,prov,observed_at=latest.timestamp,reject_older=True)
    def current_state(self,robot_id,*,at=None):
        if robot_id not in self.robots:raise KeyError('unknown robot identity')
        fused=self.fuse(robot_id,at=at)
        if fused.status!='CURRENT':return {'robot_id':robot_id,'status':fused.status,'current':False,'state':{},'freshness':'STALE' if fused.status=='STALE_OR_UNAVAILABLE' else 'CONFLICT','provenance':fused.provenance,'conflicts':fused.conflicts}
        newest=max((self.store.load_perception_observation(x) for x in fused.observation_ids),key=lambda o:_iso(o.timestamp));fr=self.freshness(newest,at=at)
        return {'robot_id':robot_id,'status':'CURRENT','current':True,'state':fused.state,'freshness':fr['state'],'age_seconds':fr['age_seconds'],'observation_ids':fused.observation_ids,'provenance':fused.provenance,'conflicts':[]}
    def require_fresh(self,robot_id):
        state=self.current_state(robot_id)
        if not state.get('current') or state.get('freshness')!='FRESH':raise RuntimeError('fresh_perception_required')
        return state
    def capability_status(self,sensor_type):
        if sensor_type not in SENSOR_TYPES:raise ValueError('unsupported sensor type')
        matches=[]
        for rid,r in self.robots.items():
            if sensor_type not in set(r.get('capabilities',[])) or rid not in self.sources:continue
            source=self.sources[rid];health=source.health() if hasattr(source,'health') else {'status':'UNKNOWN'};matches.append({'robot_id':rid,'health':health})
        connected=any(x['health'].get('status')=='CONNECTED' for x in matches);sim_verified=any(x['health'].get('status')=='CONNECTED' and x['health'].get('simulation') is True for x in matches)
        return {'sensor_type':sensor_type,'capability_exists':True,'connected':connected,'live_verified':False,'simulation_live_verified':sim_verified,'sources':matches}
    def semantic_status(self,sensor_type):
        if sensor_type not in {'camera','depth'}:return {'status':'NOT_REQUIRED','sensor_type':sensor_type}
        if self.model_manager is None:return {'status':'EXTERNALLY_BLOCKED','required_capabilities':['perception','multimodal']}
        route=self.model_manager.route(['perception','multimodal'],input_modalities=['image'],output_modalities=['text'])
        return {'status':'AVAILABLE' if route.selected else 'EXTERNALLY_BLOCKED','required_capabilities':['perception','multimodal'],'route':route.to_dict()}
