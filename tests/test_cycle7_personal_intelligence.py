import tempfile,unittest
from pathlib import Path
from sparkle_gen2.audit import AuditLog
from sparkle_gen2.capability_status import CapabilityMatrix,CapabilityState
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.personal_data import PersonalDataOrchestrator

class G:
    def health(self):return {'tools':['memory_search','knowledge_search','project_search','project_tasks','learning_progress','research_workspace']}
    def invoke(self,t,a):return ToolObservation(True,t,{'args':a},{'verified':True})

class Cycle7PersonalIntelligenceTests(unittest.TestCase):
    def test_personal_sources_resolve_exact_gen1_tools(self):
        o=PersonalDataOrchestrator(G());self.assertTrue(all(o.available_sources().values()))
        r=o.retrieve('memory','python',limit=3);self.assertEqual(r['tool'],'memory_search');self.assertTrue(r['verification']['verified'])
        with self.assertRaises(KeyError):o.retrieve('email','x')
    def test_capability_matrix_has_no_ambiguous_terminal_states(self):
        m=CapabilityMatrix();m.set(CapabilityState('voice','EXTERNALLY_BLOCKED','harness green','STT/TTS provider'))
        m.set(CapabilityState('core','LIVE_VERIFIED','tests'))
        self.assertEqual(m.unresolved(),[])
        with self.assertRaises(ValueError):CapabilityState('x','PARTIAL','none')
    def test_audit_hash_chain_detects_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'audit.sqlite3';a=AuditLog(path);a.append('goal',{'id':'g1'});a.append('tool',{'name':'x'});self.assertTrue(a.verify())
            with a.connect() as db:db.execute("UPDATE audit SET payload='{}' WHERE id=1")
            self.assertFalse(a.verify())

if __name__=='__main__':unittest.main()
