import tempfile,unittest,uuid
from datetime import UTC,datetime,timedelta
from pathlib import Path

from sparkle.system import SparkleSystem
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.environment_gateway import EnvironmentGateway
from sparkle_gen2.gen1 import LocalGen1Gateway
from sparkle_gen2.model_manager import CapabilityRouter,ModelCapabilityManager
from sparkle_gen2.models import ModelProvenance,PlanProposal,PlanProposalStep
from sparkle_gen2.perception import PerceptionService,ROS2PosePerceptionAdapter,SENSOR_TYPES
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.ros2_adapter import ROS2GatewayAdapter
from sparkle_gen2.ros2_live import ROS2ParameterSafetyController,TurtleSimROS2Node
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.world_model import WorldModel

class CLI:
    def __init__(self):self.x=1.0;self.y=2.0;self.theta=0.0;self.estop=False;self.available=True
    def run(self,args,timeout=10):
        if args[:2]==['node','list']:return '/turtlesim\n/sparkle_safety_controller' if self.available else ''
        if args[:2]==['topic','echo']:
            if not self.available:raise RuntimeError('sensor offline')
            return f'x: {self.x}\ny: {self.y}\ntheta: {self.theta}\n'
        if args[:2]==['service','call']:
            text=args[-1]
            import re
            m=re.search(r'linear:\s*(-?[0-9.]+)',text);a=re.search(r'angular:\s*(-?[0-9.]+)',text)
            self.x+=float(m.group(1)) if m else 0.0;self.theta+=float(a.group(1)) if a else 0.0;return 'ok'
        if args[:2]==['param','get']:
            if args[-1]=='estop_active':return f'Boolean value is: {str(self.estop)}'
            if args[-1]=='max_distance':return 'Double value is: 0.5'
            if args[-1]=='max_angle':return 'Double value is: 0.5'
        raise RuntimeError(args)

def payload(*,robot='r1',device='d1',sensor='pose',when=None,data=None,source=None,confidence=.9,otype=None):
    return {'device_id':device,'robot_id':robot,'sensor_type':sensor,'timestamp':when or datetime.now(UTC).isoformat(),'frame':'map','observation_type':otype or sensor,'data':data or ({'x':1.0,'y':2.0,'theta':0.0} if sensor=='pose' else {'value':50}),'confidence':confidence,'source':source or {'kind':'simulation','adapter':'test'},'provenance':{'test':True}}

def service(d,**kw):
    store=Gen2Store(Path(d)/'g2.db');world=WorldModel(store);svc=PerceptionService(store,world,**kw);svc.register_robot('r1',device_id='d1',capabilities=list(SENSOR_TYPES));return store,world,svc

class Cycle54PerceptionTests(unittest.TestCase):
    def test_schema_identity_provenance_and_confidence_are_separate_from_verification(self):
        with tempfile.TemporaryDirectory() as d:
            store,world,svc=service(d);p=payload(confidence=.92);a=svc.normalize(p,verified=False);b=svc.normalize(dict(p),verified=False);self.assertEqual(a.observation_id,b.observation_id);self.assertEqual(a.confidence,.92);self.assertFalse(a.verified);result=svc.process(p,verified=False);self.assertTrue(result['world_updated']);node=world.nodes['r1'];self.assertEqual(node.provenance['observation_id'],a.observation_id);self.assertFalse(result['fusion']['provenance'][0]['verified'])

    def test_sensor_contract_lists_required_types_and_rejects_unknown_or_malformed(self):
        self.assertTrue({'camera','lidar','depth','imu','odometry','gps','joint_state','pose','battery','proximity'}<=SENSOR_TYPES)
        with tempfile.TemporaryDirectory() as d:
            _,_,svc=service(d)
            with self.assertRaisesRegex(ValueError,'unsupported sensor'):svc.normalize(payload(sensor='thermal'),verified=True)
            bad=payload();bad.pop('source')
            with self.assertRaisesRegex(ValueError,'fields'):svc.normalize(bad,verified=True)
            bad=payload();bad['source']={}
            with self.assertRaisesRegex(ValueError,'source'):svc.normalize(bad,verified=True)

    def test_robot_identity_and_device_binding_reject_phantom_robot(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,svc=service(d)
            with self.assertRaisesRegex(KeyError,'unknown robot'):svc.process(payload(robot='phantom'),verified=True)
            with self.assertRaisesRegex(ValueError,'identity mismatch'):svc.process(payload(device='other'),verified=True)

    def test_fresh_stale_expired_and_stale_not_current(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,svc=service(d,fresh_seconds=5,expire_seconds=20);now=datetime.now(UTC);fresh=svc.normalize(payload(when=(now-timedelta(seconds=2)).isoformat()),verified=True);stale=svc.normalize(payload(when=(now-timedelta(seconds=10)).isoformat()),verified=True);expired=svc.normalize(payload(when=(now-timedelta(seconds=30)).isoformat()),verified=True)
            self.assertEqual(svc.freshness(fresh,at=now)['state'],'FRESH');self.assertEqual(svc.freshness(stale,at=now)['state'],'STALE');self.assertEqual(svc.freshness(expired,at=now)['state'],'EXPIRED');svc.process(stale.to_dict()|{'observation_id':None} if False else payload(when=(now-timedelta(seconds=10)).isoformat()),verified=True);state=svc.current_state('r1',at=now);self.assertFalse(state['current']);self.assertEqual(state['status'],'STALE_OR_UNAVAILABLE')

    def test_same_robot_pose_battery_fusion_and_different_robot_isolation(self):
        with tempfile.TemporaryDirectory() as d:
            store,world,svc=service(d);svc.register_robot('r2',device_id='d2',capabilities=['pose']);svc.process(payload(sensor='pose'),verified=True);svc.process(payload(sensor='battery',data={'percent':81.0}),verified=True);f=svc.fuse('r1');self.assertEqual(f.status,'CURRENT');self.assertEqual(f.state['battery']['percent'],81.0);svc.process(payload(robot='r2',device='d2',data={'x':9.0,'y':9.0,'theta':0.0}),verified=True);self.assertEqual(svc.current_state('r1')['state']['pose']['x'],1.0);self.assertEqual(svc.current_state('r2')['state']['pose']['x'],9.0)

    def test_conflicting_different_sources_do_not_silently_overwrite_world(self):
        with tempfile.TemporaryDirectory() as d:
            _,world,svc=service(d,pose_conflict_tolerance=.1);a=payload(data={'x':1,'y':2,'theta':0},source={'kind':'simulation','adapter':'a'});svc.process(a,verified=True);before=world.nodes['r1'].state['pose']['x'];b=payload(data={'x':5,'y':2,'theta':0},source={'kind':'simulation','adapter':'b'},when=(datetime.now(UTC)+timedelta(milliseconds=1)).isoformat());out=svc.process(b,verified=True);self.assertEqual(out['fusion']['status'],'CONFLICT');self.assertFalse(out['world_updated']);self.assertEqual(world.nodes['r1'].state['pose']['x'],before);self.assertTrue(out['fusion']['conflicts'])

    def test_sequential_same_source_motion_supersedes_without_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            _,world,svc=service(d);src={'kind':'simulation','adapter':'same'};svc.process(payload(data={'x':1,'y':2,'theta':0},source=src),verified=True);svc.process(payload(data={'x':1.4,'y':2,'theta':0},source=src,when=(datetime.now(UTC)+timedelta(milliseconds=1)).isoformat()),verified=True);self.assertEqual(svc.current_state('r1')['status'],'CURRENT');self.assertAlmostEqual(world.nodes['r1'].state['pose']['x'],1.4)

    def test_ros2_pose_adapter_normalizes_real_gateway_contract(self):
        cli=CLI();gateway=ROS2GatewayAdapter(TurtleSimROS2Node(cli),ROS2ParameterSafetyController(cli),allowed_actions={'status','move'});adapter=ROS2PosePerceptionAdapter(gateway);raw=adapter.observe();self.assertEqual(raw['robot_id'],'turtle1');self.assertEqual(raw['sensor_type'],'pose');self.assertEqual(raw['source']['topic'],'/turtle1/pose');self.assertEqual(raw['data']['x'],1.0);self.assertEqual(adapter.health()['status'],'CONNECTED')

    def test_unavailable_source_is_explicit_and_does_not_create_world_node(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.db');world=WorldModel(store);svc=PerceptionService(store,world);svc.register_robot('r1',device_id='d1',source=None,capabilities=['pose']);self.assertEqual(svc.observe('r1')['status'],'UNAVAILABLE');self.assertNotIn('r1',world.nodes)

    def test_restart_preserves_observation_but_recomputes_freshness(self):
        with tempfile.TemporaryDirectory() as d:
            store,world,svc=service(d,fresh_seconds=2,expire_seconds=20);when=(datetime.now(UTC)-timedelta(seconds=1)).isoformat();out=svc.process(payload(when=when),verified=True);oid=out['observation']['observation_id'];world2=WorldModel(Gen2Store(Path(d)/'g2.db'));svc2=PerceptionService(Gen2Store(Path(d)/'g2.db'),world2,fresh_seconds=2,expire_seconds=20);svc2.register_robot('r1',device_id='d1',capabilities=['pose']);self.assertEqual(svc2.store.load_perception_observation(oid).observation_id,oid);future=datetime.now(UTC)+timedelta(seconds=5);self.assertEqual(svc2.current_state('r1',at=future)['status'],'STALE_OR_UNAVAILABLE');self.assertGreater(world2.freshness('r1',at=future),2)

    def test_idempotent_same_observation_is_one_persisted_record(self):
        with tempfile.TemporaryDirectory() as d:
            store,_,svc=service(d);p=payload();a=svc.process(p,verified=True);b=svc.process(dict(p),verified=True);self.assertEqual(a['observation']['observation_id'],b['observation']['observation_id']);self.assertEqual(len(store.perception_observations(robot_id='r1')),1)

    def test_capability_exists_connected_and_live_are_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.db');world=WorldModel(store);svc=PerceptionService(store,world);svc.register_robot('r1',device_id='d1',capabilities=['camera']);s=svc.capability_status('camera');self.assertTrue(s['capability_exists']);self.assertFalse(s['connected']);self.assertFalse(s['live_verified']);self.assertFalse(s['simulation_live_verified'])

    def test_perception_world_context_ages_out_at_perception_boundary(self):
        from sparkle_gen2.context_sources import PersonalContextAssembler
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.db');world=WorldModel(store);old=(datetime.now(UTC)-timedelta(seconds=20)).isoformat();world.observe('r1','robot',{'pose':{'x':1}}, {'source':'perception','observation_id':'o1'},observed_at=old);ctx=PersonalContextAssembler(store=store,world=world).gather('where is robot');self.assertFalse(any(x['source']=='world_state' for x in ctx['items']))
            world.observe('r1','robot',{'pose':{'x':2}}, {'source':'perception','observation_id':'o2'},observed_at=datetime.now(UTC).isoformat());ctx=PersonalContextAssembler(store=store,world=world).gather('where is robot');self.assertTrue(any(x['source']=='world_state' for x in ctx['items']))

    def test_future_perception_multimodal_model_routes_by_capability(self):
        import json
        from sparkle.registry import ModelRegistry
        with tempfile.TemporaryDirectory() as d:
            cfg={'active_model':'reason','models':[{'id':'reason','provider':'nvidia','model_id':'nvidia/reason','adapter':'nvidia_chat_completions','roles':['reasoning'],'input_modalities':['text'],'output_modalities':['text'],'enabled':True,'allow_fallback':False},{'id':'vision','provider':'nvidia','model_id':'nvidia/vision','adapter':'nvidia_chat_completions','roles':['perception','multimodal'],'input_modalities':['text','image'],'output_modalities':['text'],'enabled':True,'allow_fallback':False}],'routing':{'default':'reason','reasoning':'reason','perception':'vision','multimodal':'vision'}};path=Path(d)/'models.json';path.write_text(json.dumps(cfg));m=ModelCapabilityManager(registry=ModelRegistry(path=path),fallback_allowed=False);route=CapabilityRouter(m).require(['perception','multimodal'],input_modalities=['image'],output_modalities=['text']);self.assertEqual(route.selected.record_id,'vision');self.assertNotEqual(route.selected.record_id,'reason')

    def test_multimodal_camera_semantics_fail_closed_on_text_only_production(self):
        with tempfile.TemporaryDirectory() as d:
            g=LocalGen1Gateway(SparkleSystem());store=Gen2Store(Path(d)/'g2.db');svc=PerceptionService(store,WorldModel(store),model_manager=g.model_manager);svc.register_robot('r1',device_id='d1',capabilities=['camera']);status=svc.semantic_status('camera');self.assertEqual(status['status'],'EXTERNALLY_BLOCKED');self.assertEqual(status['required_capabilities'],['perception','multimodal'])

    def test_personal_agent_grounded_pose_query(self):
        with tempfile.TemporaryDirectory() as d:
            cli=CLI();ros=ROS2GatewayAdapter(TurtleSimROS2Node(cli),ROS2ParameterSafetyController(cli),allowed_actions={'status','move'});store=Gen2Store(Path(d)/'g2.db');world=WorldModel(store);svc=PerceptionService(store,world);svc.register_robot('turtle1',device_id='ros2-sim',source=ROS2PosePerceptionAdapter(ros),capabilities=['pose'])
            base=LocalGen1Gateway(SparkleSystem());gen1=EnvironmentGateway(base,ros2=ros);proposal=PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('see','Observe current robot pose',['perception_observe'],[],['fresh current pose'],{'robot_id':'turtle1'},30,0)],[{'description':'fresh pose verified','verification_method':'all_steps_verified'}],'LOW',.99,[],'test-only');agent=PersonalAgent(store,gen1,planner=StaticPlanner(proposal),perception_service=svc);r=agent.start('Where is Robot-01?',user_id='u');self.assertEqual(r['status'],'COMPLETED');self.assertIn('Current simulated perception',r['text']);self.assertIn('x 1.00',r['text']);self.assertIn('observation obs_',r['text']);self.assertEqual(world.nodes['turtle1'].provenance['source'],'perception')

    def test_action_requires_fresh_perception_then_reobserves_and_verifies(self):
        with tempfile.TemporaryDirectory() as d:
            cli=CLI();ros=ROS2GatewayAdapter(TurtleSimROS2Node(cli),ROS2ParameterSafetyController(cli),allowed_actions={'status','move'});store=Gen2Store(Path(d)/'g2.db');world=WorldModel(store);svc=PerceptionService(store,world);svc.register_robot('turtle1',device_id='ros2-sim',source=ROS2PosePerceptionAdapter(ros),capabilities=['pose']);base=LocalGen1Gateway(SparkleSystem());gen1=EnvironmentGateway(base,ros2=ros)
            steps=[PlanProposalStep('before','Observe robot before movement',['perception_observe'],[],['fresh pose'],{'robot_id':'turtle1'},30,0),PlanProposalStep('move','Move simulation safely',['ros2_sim_move'],['before'],['independent ROS2 pose reread'],{'distance':.2,'angle':0.0},30,0),PlanProposalStep('after','Observe robot after movement',['perception_observe'],['move'],['fresh changed pose'],{'robot_id':'turtle1'},30,0)];proposal=PlanProposal(uuid.uuid4().hex,'x',steps,[{'description':'move and perception verified','verification_method':'all_steps_verified'}],'MEDIUM',.99,[],'test-only');agent=PersonalAgent(store,gen1,planner=StaticPlanner(proposal),perception_service=svc);first=agent.start('Observe, move, and verify the simulated robot.',user_id='u');self.assertEqual(first['status'],'WAITING');self.assertEqual(len(first['approvals']),1);self.assertAlmostEqual(cli.x,1.0);agent.decide_approval(first['approvals'][0],'approve',actor='human-reviewer');done=agent.resume(first['goal_id']);self.assertEqual(done['status'],'COMPLETED');self.assertAlmostEqual(cli.x,1.2);obs=store.perception_observations(robot_id='turtle1');self.assertEqual(len(obs),2);self.assertAlmostEqual(world.nodes['turtle1'].state['pose']['x'],1.2);self.assertIn('independently verified',done['text'])

    def test_move_without_fresh_perception_is_blocked_before_ros2_action(self):
        with tempfile.TemporaryDirectory() as d:
            cli=CLI();ros=ROS2GatewayAdapter(TurtleSimROS2Node(cli),ROS2ParameterSafetyController(cli),allowed_actions={'status','move'});store=Gen2Store(Path(d)/'g2.db');world=WorldModel(store);svc=PerceptionService(store,world);svc.register_robot('turtle1',device_id='ros2-sim',source=ROS2PosePerceptionAdapter(ros),capabilities=['pose']);gen1=EnvironmentGateway(LocalGen1Gateway(SparkleSystem()),ros2=ros);proposal=PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('move','Move without observation',['ros2_sim_move'],[],['verified'],{'distance':.2,'angle':0.0},30,0)],[{'description':'move verified','verification_method':'all_steps_verified'}],'MEDIUM',.9,[],'test-only');agent=PersonalAgent(store,gen1,planner=StaticPlanner(proposal),perception_service=svc);first=agent.start('Move now.',user_id='u');agent.decide_approval(first['approvals'][0],'approve',actor='human-reviewer');done=agent.resume(first['goal_id']);self.assertNotEqual(done['status'],'COMPLETED');self.assertAlmostEqual(cli.x,1.0)

    def test_estop_still_blocks_action_after_fresh_perception(self):
        with tempfile.TemporaryDirectory() as d:
            cli=CLI();ros=ROS2GatewayAdapter(TurtleSimROS2Node(cli),ROS2ParameterSafetyController(cli),allowed_actions={'status','move'});store=Gen2Store(Path(d)/'g2.db');svc=PerceptionService(store,WorldModel(store));svc.register_robot('turtle1',device_id='ros2-sim',source=ROS2PosePerceptionAdapter(ros),capabilities=['pose']);self.assertEqual(svc.observe('turtle1')['status'],'OBSERVED');cli.estop=True
            with self.assertRaisesRegex(RuntimeError,'emergency_stop'):ros.invoke('move',{'distance':.1,'angle':0.0})

if __name__=='__main__':unittest.main()
