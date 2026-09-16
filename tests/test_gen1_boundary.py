import unittest
from sparkle_gen2.gen1 import LocalGen1Gateway

class Gen1BoundaryTests(unittest.TestCase):
    def test_gen1_health_and_calculator_contract(self):
        gateway=LocalGen1Gateway(); health=gateway.health(); self.assertTrue(health["available"]); self.assertIn("calculator",health["tools"])
        result=gateway.invoke("calculator",{"expression":"2+2"}); self.assertTrue(result.ok); self.assertTrue(result.verification["verified"])
    def test_gen1_unknown_tool_fails_closed(self):
        result=LocalGen1Gateway().invoke("arbitrary_shell",{"command":"id"}); self.assertFalse(result.ok); self.assertFalse(result.verification["verified"])
if __name__=="__main__": unittest.main()
