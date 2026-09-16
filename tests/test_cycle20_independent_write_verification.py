import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from sparkle.system import SparkleSystem
from sparkle_gen2.gen1 import LocalGen1Gateway

class Cycle20Tests(unittest.TestCase):
    def _gateway(self,d):
        env=patch.dict(os.environ,{'SPARKLE_DATA_DIR':str(Path(d)/'gen1')});env.start();self.addCleanup(env.stop)
        return LocalGen1Gateway(SparkleSystem())
    def test_scaffold_verify_package_are_independently_reread(self):
        with tempfile.TemporaryDirectory() as d:
            g=self._gateway(d)
            sc=g.invoke('workspace_scaffold',{'project_name':'verifyapp','files':{'main.py':'x=1\n'},'approved':True});self.assertTrue(sc.ok);self.assertTrue(sc.verification['verified']);self.assertIn('file digests',sc.verification['method'])
            vr=g.invoke('workspace_verify',{'project_name':'verifyapp','checks':[{'type':'python_compile','path':'main.py'}],'approved':True});self.assertTrue(vr.verification['verified']);self.assertIn('verification run',vr.verification['method'])
            pkg=g.invoke('workspace_package',{'project_name':'verifyapp','approved':True});self.assertTrue(pkg.verification['verified']);self.assertIn('package digest',pkg.verification['method'])
    def test_read_only_tool_is_not_described_as_state_change_verification(self):
        with tempfile.TemporaryDirectory() as d:
            g=self._gateway(d);obs=g.invoke('calculator',{'expression':'2+2'});self.assertTrue(obs.verification['verified']);self.assertIn('read-only',obs.verification['method'])
    def test_agent_install_re_reads_persistent_store(self):
        with tempfile.TemporaryDirectory() as d:
            g=self._gateway(d);obs=g.invoke('agent_install',{'name':'helperx','capability':'general','purpose':'A bounded generated helper for testing.','instructions':'Perform only bounded approved tasks for testing.','tools':['calculator'],'keywords':['helper'],'approved':True})
            self.assertTrue(obs.ok);self.assertTrue(obs.verification['verified']);self.assertIn('persistent store',obs.verification['method'])
if __name__=='__main__':unittest.main()
