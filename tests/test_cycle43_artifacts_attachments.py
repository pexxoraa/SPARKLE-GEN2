import hashlib,tempfile,unittest
from pathlib import Path
from sparkle_gen2.gen1 import LocalGen1Gateway
class Artifacts:
    def __init__(self,root):self.artifact_root=root;self.row={'artifact_id':1,'project_name':'demo','artifact_name':'demo/a.zip','artifact_sha256':''};(root/'demo').mkdir(parents=True);data=b'zip-content';(root/'demo/a.zip').write_bytes(data);self.row['artifact_sha256']=hashlib.sha256(data).hexdigest()
    def list(self,limit=20):return [dict(self.row)]
class System:
    def __init__(self,root):self.artifacts=Artifacts(root)
class Cycle43Tests(unittest.TestCase):
    def test_artifact_download_rechecks_digest_and_bounds_path(self):
        with tempfile.TemporaryDirectory() as d:
            g=LocalGen1Gateway.__new__(LocalGen1Gateway);g.system=System(Path(d));v=g.artifact_content(1);self.assertEqual(v['content'],b'zip-content')
            (Path(d)/'demo/a.zip').write_bytes(b'tampered')
            with self.assertRaisesRegex(RuntimeError,'digest'):g.artifact_content(1)
