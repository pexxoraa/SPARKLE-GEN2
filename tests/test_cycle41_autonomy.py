import tempfile,unittest
from pathlib import Path
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.autonomy import AutonomyController
class Cycle41Tests(unittest.TestCase):
    def test_autonomy_is_persistent_and_never_overrides_approval_or_deny(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.db';a=AutonomyController(Gen2Store(p));self.assertEqual(a.get()['mode'],'APPROVAL_REQUIRED');self.assertFalse(a.allows_unattended('ALLOW','LOW'))
            a.set('LIMITED_AUTONOMOUS');b=AutonomyController(Gen2Store(p));self.assertTrue(b.allows_unattended('ALLOW','LOW'));self.assertFalse(b.allows_unattended('REQUIRE_APPROVAL','LOW'));self.assertFalse(b.allows_unattended('DENY','LOW'))
            b.set('MANUAL');self.assertFalse(b.allows_unattended('ALLOW','LOW'))
    def test_invalid_mode_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):AutonomyController(Gen2Store(Path(d)/'x.db')).set('UNLIMITED')
if __name__=='__main__':unittest.main()
