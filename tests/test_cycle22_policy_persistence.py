import tempfile,unittest,uuid
from pathlib import Path
from sparkle_gen2.models import Permission,PermissionEffect,PermissionStatus,RiskEvaluation,RiskLevel
from sparkle_gen2.storage import Gen2Store

class Cycle22Tests(unittest.TestCase):
    def test_permission_and_risk_reload_as_typed_objects_after_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'x.db';s=Gen2Store(path);gid='g1'
            p=Permission(uuid.uuid4().hex,'user','memory_write','remember',PermissionEffect.REQUIRE_APPROVAL,PermissionStatus.ACTIVE,'policy','now',None,{})
            r=RiskEvaluation(uuid.uuid4().hex,'remember','memory_write',RiskLevel.MEDIUM,'write action','policy','now','USER_APPROVAL_AND_GEN1_POLICY')
            s.save_permission(gid,p);s.save_risk(gid,r)
            restarted=Gen2Store(path);rp=restarted.permissions_for_goal(gid)[0];rr=restarted.risks_for_goal(gid)[0]
            self.assertIsInstance(rp.effect,PermissionEffect);self.assertEqual(rp.status,PermissionStatus.ACTIVE)
            self.assertIsInstance(rr.level,RiskLevel);self.assertEqual(rr.level,RiskLevel.MEDIUM)
if __name__=='__main__':unittest.main()
