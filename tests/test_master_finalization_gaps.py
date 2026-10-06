import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from sparkle_gen2.modes import RoboticsEngineerMode
from sparkle_gen2.rollback import RollbackManager
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.world_model import WorldModel

class Robot:
    def __init__(self):self.calls=[]
    def health(self):return {'status':'HEALTHY','safety':'READY'}
    def command(self,action,payload,*,approved=False):
        if not approved:raise PermissionError('approval_required')
        self.calls.append((action,dict(payload)));return {'accepted':True,'action':action}
    def execute_verified(self,action,payload,*,approved=False):
        if not approved:raise PermissionError('approval_required')
        self.calls.append((action,dict(payload)))
        return {'result':{'pose':{'x':1.0}},'after':{'pose':{'x':1.0},'status':'IDLE'},'verification':{'verified':True,'method':'independent pose reread'}}

class Perception:
    def current_state(self,robot_id):return {'robot_id':robot_id,'freshness':'FRESH','observations':{'pose':{'x':0.0}}}
class Documents:
    def list(self,*,user_id):return [SimpleNamespace(document_id='d1',filename='robot-notes.pdf',media_type='application/pdf',status='READY',classification='PRIVATE',updated_at='now')]

class MasterFinalizationGapTests(unittest.TestCase):
    def test_generic_rollback_is_restart_safe_and_verified(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'g.db';m=RollbackManager(Gen2Store(path))
            r=m.prepare('goal-1','replace configuration','restore_previous',recovery_reference='artifact:safe-backup')
            self.assertEqual(RollbackManager(Gen2Store(path)).inspect(r.rollback_id).recovery_reference,'artifact:safe-backup')
            with self.assertRaises(PermissionError):m.execute(r.rollback_id,lambda _: {'verified':True})
            done=m.execute(r.rollback_id,lambda s:{'verified':s=='restore_previous','method':'reread'},approved=True)
            self.assertEqual(done.status,'VERIFIED');self.assertEqual(RollbackManager(Gen2Store(path)).inspect(r.rollback_id).status,'VERIFIED')
            self.assertEqual(len(m.provenance(r.rollback_id)['strategy_sha256']),64)

    def test_interrupted_rollback_fails_closed_after_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'g.db';m=RollbackManager(Gen2Store(path));r=m.prepare('g','action','restore');r.status='EXECUTING';m._save(r)
            recovered=RollbackManager(Gen2Store(path));self.assertEqual(recovered.restart_reconcile(),[r.rollback_id])
            rr=RollbackManager(Gen2Store(path)).inspect(r.rollback_id);self.assertEqual(rr.status,'FAILED');self.assertFalse(rr.evidence['verified'])

    def test_robotics_engineer_workspace_is_read_only_aggregation(self):
        with tempfile.TemporaryDirectory() as d:
            world=WorldModel(Gen2Store(Path(d)/'g.db'));robot=Robot()
            exps=SimpleNamespace(items={'e1':SimpleNamespace(experiment_id='e1',status='COMPLETED',verification_state='VERIFIED',project_id='robotics',research_id='r1',updated_at='now')})
            mode=RoboticsEngineerMode(robot,world,perception=Perception(),experiments=exps,documents=Documents())
            view=mode.workspace('robot-1',user_id='u');self.assertEqual(view['robot']['status'],'HEALTHY')
            self.assertEqual(view['perception']['status'],'AVAILABLE');self.assertEqual(view['experiments'][0]['verification_state'],'VERIFIED')
            self.assertEqual(view['documents'][0]['document_id'],'d1');self.assertEqual(robot.calls,[])

    def test_robotics_engineer_verified_motion_preserves_gate_and_provenance(self):
        world=WorldModel();robot=Robot();mode=RoboticsEngineerMode(robot,world)
        with self.assertRaises(PermissionError):mode.move_verified('move',{'distance':0.1},approved=False,robot_id='r1')
        result=mode.move_verified('move',{'distance':0.1},approved=True,robot_id='r1')
        self.assertTrue(result['verification']['verified']);self.assertEqual(len(robot.calls),1)
        self.assertEqual(world.nodes['r1'].provenance['source'],'robot_gateway_verified_action')

    def test_robotics_engineer_diagnostics_are_evidence_based(self):
        class BlockedRobot(Robot):
            def health(self):return {'status':'EXTERNALLY_BLOCKED','reason':'target unavailable'}
        report=RoboticsEngineerMode(BlockedRobot(),WorldModel()).diagnose('r1')
        self.assertEqual(report['status'],'ATTENTION');self.assertIn('robot_gateway',{x['category'] for x in report['findings']})

if __name__=='__main__':unittest.main()

class KnowledgeGraphFinalizationTests(unittest.TestCase):
    def test_cross_source_contradiction_is_persisted_and_resolvable(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'g.db';w=WorldModel(Gen2Store(path))
            w.observe('project-x','project',{'status':'active'},{'source':'project_store'})
            w.observe('project-x','project',{'status':'paused'},{'source':'calendar_sync'})
            conflicts=w.contradictions('project-x');self.assertEqual(len(conflicts),1)
            cid=conflicts[0]['conflict_id'];self.assertNotEqual(conflicts[0]['previous_state_sha256'],conflicts[0]['incoming_state_sha256'])
            recovered=WorldModel(Gen2Store(path));self.assertEqual(recovered.contradictions('project-x')[0]['conflict_id'],cid)
            recovered.resolve_contradiction('project-x',cid,{'status':'paused'},{'source':'human_resolution'})
            self.assertEqual(recovered.contradictions('project-x'),[])
            final=WorldModel(Gen2Store(path));self.assertEqual(final.nodes['project-x'].state['status'],'paused')
            self.assertTrue(final.contradictions('project-x',include_resolved=True)[0]['resolved'])

    def test_relationship_upsert_and_bounded_query(self):
        with tempfile.TemporaryDirectory() as d:
            w=WorldModel(Gen2Store(Path(d)/'g.db'));w.observe('person','person',{'name':'A'},{'source':'user'});w.observe('project','project',{'name':'P'},{'source':'project'})
            first=w.upsert_relation('person','owns','project',{'source':'user'},confidence=.8)
            second=w.upsert_relation('person','owns','project',{'source':'verified_project'},confidence=1.0)
            self.assertEqual(first.edge_id,second.edge_id);self.assertEqual(len(w.edges),1);self.assertEqual(second.provenance['source'],'verified_project')
            q=w.query(kind='project',relation='owns',source='person',limit=10);self.assertEqual(len(q['nodes']),1);self.assertEqual(len(q['edges']),1)
