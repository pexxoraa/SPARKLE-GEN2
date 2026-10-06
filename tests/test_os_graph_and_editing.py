import tempfile,unittest
from pathlib import Path
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.personal_core import PersonalCore

class Dummy:
    pass

class OSGraphEditingTests(unittest.TestCase):
    def core(self,d):
        store=Gen2Store(Path(d)/'g.db')
        # bypass full runtime: exercise authoritative storage-backed methods directly
        class C:
            pass
        core=C();core.store=store
        from sparkle_gen2.personal_core import PersonalCore
        # construct only for methods requiring store; normal construction is integration-tested elsewhere
        core._os_text=PersonalCore._os_text
        core.create_manual_goal=PersonalCore.create_manual_goal.__get__(core,C)
        core.update_manual_goal=PersonalCore.update_manual_goal.__get__(core,C)
        core.save_manual_record=PersonalCore.save_manual_record.__get__(core,C)
        return core
    def test_goal_metadata_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            c=self.core(d)
            g=c.create_manual_goal('Ship module',description='Core OS',priority=8,deadline='2026-12-01',owner_user_id='user')['goal']
            self.assertEqual(g['priority'],8)
            self.assertEqual(g['deadline'],'2026-12-01')
            c.update_manual_goal(g['goal_id'],{'metadata':{'milestones':['alpha','beta'],'project_id':'project_1'}},owner_user_id='user')
            reread=c.store.load_goal(g['goal_id']).to_dict()
            self.assertEqual(reread['metadata']['milestones'],['alpha','beta'])
            self.assertEqual(reread['metadata']['project_id'],'project_1')
    def test_record_relationship_fields_persist(self):
        with tempfile.TemporaryDirectory() as d:
            c=self.core(d)
            p=c.save_manual_record('project','Robot platform',metadata={'goal_id':'g1','milestones':['m1']},owner_user_id='user')
            self.assertEqual(c.store.load_os_record(p['record_id'])['metadata']['goal_id'],'g1')
            self.assertEqual(c.store.load_os_record(p['record_id'])['metadata']['milestones'],['m1'])

if __name__=='__main__':unittest.main()
