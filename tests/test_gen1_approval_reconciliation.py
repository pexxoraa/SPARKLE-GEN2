import os,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from sparkle.system import SparkleSystem
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.gen1 import LocalGen1Gateway
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.storage import Gen2Store

def memory_plan():
    return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('remember','Remember approved preference',['memory_write'],[],['proposal reviewed'],{'category':'preferences','key':'cycle2_test','value':'remember this','importance':.8},30,0)],[{'description':'memory operation verified','verification_method':'all_steps_verified'}],'MEDIUM',.9,[],'test')

class Gen1ApprovalReconciliationTests(unittest.TestCase):
    def _start_pending(self,d):
        data=Path(d)/'gen1';data.mkdir();db=Path(d)/'gen2.sqlite3'
        env=patch.dict(os.environ,{'SPARKLE_DATA_DIR':str(data)})
        env.start();self.addCleanup(env.stop)
        system=SparkleSystem();gateway=LocalGen1Gateway(system);planner=StaticPlanner(memory_plan());agent=PersonalAgent(Gen2Store(db),gateway,planner=planner)
        first=agent.start('remember approved preference');self.assertEqual(first['status'],'WAITING');self.assertEqual(len(first['approvals']),1)
        agent.decide_approval(first['approvals'][0],'approve')
        second=agent.resume(first['goal_id']);self.assertEqual(second['status'],'WAITING');self.assertEqual(len(second['gen1_approvals']),1)
        proposal_id=second['gen1_approvals'][0]
        rows=system.memory_review.list(limit=100,status='pending');row=next(r for r in rows if r['id']==proposal_id)
        return db,system,gateway,planner,second,row
    def test_gen1_operator_approval_reconciles_without_duplicate_write(self):
        with tempfile.TemporaryDirectory() as d:
            db,system,gateway,planner,second,row=self._start_pending(d)
            system.memory_review.review(row['id'],row['digest'],'approve',reviewer='cli')
            restarted=PersonalAgent(Gen2Store(db),gateway,planner=planner);final=restarted.resume(second['goal_id'])
            self.assertEqual(final['status'],'COMPLETED');self.assertEqual(system.memory_review.list(limit=100,status='pending'),[])
            traces=Gen2Store(db).operation_traces(trace_id=final['trace_id']);self.assertTrue(any(t['kind']=='verification' and t['status']=='VERIFIED' for t in traces))
            memories=system.memory.search('remember this',category='preferences',limit=10);self.assertTrue(any(m['key']=='cycle2_test' for m in memories))
    def test_gen1_operator_rejection_blocks_without_duplicate_write(self):
        with tempfile.TemporaryDirectory() as d:
            db,system,gateway,planner,second,row=self._start_pending(d)
            system.memory_review.review(row['id'],row['digest'],'reject',reviewer='cli')
            restarted=PersonalAgent(Gen2Store(db),gateway,planner=planner);final=restarted.resume(second['goal_id'])
            self.assertEqual(final['status'],'BLOCKED');self.assertEqual(system.memory_review.list(limit=100,status='pending'),[])
            self.assertEqual(system.memory.search('remember this',category='preferences',limit=10),[])

if __name__=='__main__':unittest.main()
