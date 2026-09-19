import os,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from sparkle.system import SparkleSystem
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.gen1 import LocalGen1Gateway,ToolObservation
from sparkle_gen2.memory_orchestration import MemoryCandidateAnalyzer
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.storage import Gen2Store

class ReadGateway:
    def health(self):return {'available':True,'tools':['calculator','memory_write']}
    def retrieve_context(self,*a):return {'source':'test','rendered':'bounded'}
    def invoke(self,tool,args):
        if tool=='calculator':return ToolObservation(True,tool,{'value':703},{'verified':True,'method':'test reread'})
        raise AssertionError('memory_write must not execute without explicit candidate approval')
    def approval_status(self,*a):return {'status':'UNKNOWN','verified':False}

def calc_plan():
    return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('calc','Verify harmless arithmetic',['calculator'],[],['verified arithmetic'],{'expression':'700+3'},30,0)],[{'description':'verified completion','verification_method':'all_steps_verified'}],'LOW',.9,[],'test')

class Cycle45CompletionMemoryTests(unittest.TestCase):
    def _complete(self,path,request,gateway=None):
        gateway=gateway or ReadGateway();agent=PersonalAgent(Gen2Store(path),gateway,planner=StaticPlanner(calc_plan()));return agent,agent.start(request)

    def test_completed_durable_preference_generates_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            agent,result=self._complete(Path(d)/'g.db','Remember that I prefer concise weekly robotics updates.')
            self.assertEqual(result['status'],'COMPLETED');self.assertEqual(len(result['memory_candidates']),1)
            c=result['memory_candidates'][0];self.assertEqual(c['value'],'I prefer concise weekly robotics updates');self.assertEqual(c['category'],'preferences');self.assertEqual(c['state'],'PROPOSED');self.assertEqual(c['goal_id'],result['goal_id']);self.assertEqual(c['trace_id'],result['trace_id'])
            self.assertIn('nothing will be stored unless you approve it',result['text'])

    def test_noop_completion_produces_zero_candidates(self):
        with tempfile.TemporaryDirectory() as d:
            _,result=self._complete(Path(d)/'g.db','Calculate 700 + 3.')
            self.assertEqual(result['status'],'COMPLETED');self.assertEqual(result['memory_candidates'],[])

    def test_secret_never_becomes_candidate(self):
        analyzer=MemoryCandidateAnalyzer()
        fake_nvidia='nvapi-'+'A'*32
        for text in (f'Remember that my API key is {fake_nvidia}.','Remember that my password is hunter2.','Remember that my token is abcdefghijklmnopqrstuvwxyz0123456789.','Remember that bearer abcdefghijklmnopqrstuvwxyz is my token.'):
            with self.subTest(text=text),tempfile.TemporaryDirectory() as d:
                _,result=self._complete(Path(d)/'g.db',text);self.assertEqual(result['memory_candidates'],[])

    def test_candidate_persists_restart_and_requires_gen1_review(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'gen1';data.mkdir();db=root/'g.db'
            with patch.dict(os.environ,{'SPARKLE_DATA_DIR':str(data)}):
                system=SparkleSystem();gateway=LocalGen1Gateway(system);agent=PersonalAgent(Gen2Store(db),gateway,planner=StaticPlanner(calc_plan()));result=agent.start('Remember that I prefer concise weekly robotics updates.')
                c=result['memory_candidates'][0];self.assertEqual(system.memory.search('concise weekly robotics updates',category='preferences',limit=10),[])
                restarted=PersonalAgent(Gen2Store(db),gateway,planner=StaticPlanner(calc_plan()));self.assertEqual(restarted.memory_candidates(result['goal_id'])[0]['candidate_id'],c['candidate_id'])
                submitted=restarted.decide_memory_candidate(c['candidate_id'],'approve',actor='user');self.assertEqual(submitted['state'],'REVIEW_PENDING');self.assertTrue(submitted['gen1_approval_id']);self.assertEqual(system.memory.search('concise weekly robotics updates',category='preferences',limit=10),[])

    def test_approved_candidate_persists_with_reverse_provenance_after_restart(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'gen1';data.mkdir();db=root/'g.db'
            with patch.dict(os.environ,{'SPARKLE_DATA_DIR':str(data)}):
                system=SparkleSystem();gateway=LocalGen1Gateway(system);agent=PersonalAgent(Gen2Store(db),gateway,planner=StaticPlanner(calc_plan()));result=agent.start('Remember that I prefer concise weekly robotics updates.');candidate=result['memory_candidates'][0];submitted=agent.decide_memory_candidate(candidate['candidate_id'],'approve',actor='user')
                row=next(r for r in system.memory_review.list(limit=100,status='pending') if r['id']==submitted['gen1_approval_id']);system.memory_review.review(row['id'],row['digest'],'approve',reviewer='cli')
                restarted=PersonalAgent(Gen2Store(db),gateway,planner=StaticPlanner(calc_plan()));persisted=restarted.reconcile_memory_candidate(candidate['candidate_id']);self.assertEqual(persisted['state'],'PERSISTED');self.assertTrue(persisted['memory_id'])
                memory=system.memory.search('concise weekly robotics updates',category='preferences',limit=10);self.assertTrue(any(str(m.get('id'))==persisted['memory_id'] or m.get('key')==persisted['memory_key'] for m in memory))
                restarted_again=PersonalAgent(Gen2Store(db),gateway,planner=StaticPlanner(calc_plan()));origin=restarted_again.memory_candidate_for_memory(persisted['memory_id']);self.assertEqual(origin['candidate_id'],candidate['candidate_id']);self.assertEqual(origin['goal_id'],result['goal_id']);self.assertEqual(origin['task_run_id'],result['task_run_id']);self.assertEqual(origin['trace_id'],result['trace_id']);self.assertTrue(origin['evidence']['verified_steps'])

    def test_rejected_candidate_never_enters_gen1_memory(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'gen1';data.mkdir();db=root/'g.db'
            with patch.dict(os.environ,{'SPARKLE_DATA_DIR':str(data)}):
                system=SparkleSystem();gateway=LocalGen1Gateway(system);agent=PersonalAgent(Gen2Store(db),gateway,planner=StaticPlanner(calc_plan()));result=agent.start('Remember that I prefer concise weekly robotics updates.');cid=result['memory_candidates'][0]['candidate_id'];rejected=agent.decide_memory_candidate(cid,'reject',actor='user');self.assertEqual(rejected['state'],'REJECTED')
                restarted=PersonalAgent(Gen2Store(db),gateway,planner=StaticPlanner(calc_plan()));self.assertEqual(restarted.memory_candidates(result['goal_id'])[0]['state'],'REJECTED');self.assertEqual(system.memory_review.list(limit=100,status='pending'),[]);self.assertEqual(system.memory.search('concise weekly robotics updates',category='preferences',limit=10),[])

    def test_gen1_review_rejection_is_persisted_without_memory(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'gen1';data.mkdir();db=root/'g.db'
            with patch.dict(os.environ,{'SPARKLE_DATA_DIR':str(data)}):
                system=SparkleSystem();gateway=LocalGen1Gateway(system);agent=PersonalAgent(Gen2Store(db),gateway,planner=StaticPlanner(calc_plan()));result=agent.start('Remember that I prefer concise weekly robotics updates.');cid=result['memory_candidates'][0]['candidate_id'];submitted=agent.decide_memory_candidate(cid,'approve',actor='user');row=next(r for r in system.memory_review.list(limit=100,status='pending') if r['id']==submitted['gen1_approval_id']);system.memory_review.review(row['id'],row['digest'],'reject',reviewer='cli')
                restarted=PersonalAgent(Gen2Store(db),gateway,planner=StaticPlanner(calc_plan()));final=restarted.reconcile_memory_candidate(cid);self.assertEqual(final['state'],'REVIEW_REJECTED');self.assertIsNone(final['memory_id']);self.assertEqual(system.memory.search('concise weekly robotics updates',category='preferences',limit=10),[])

    def test_completion_reprocessing_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'g.db';agent,result=self._complete(path,'Remember that I prefer concise weekly robotics updates.');first=result['memory_candidates'][0];again=agent.resume(result['goal_id']);self.assertEqual(len(again['memory_candidates']),1);self.assertEqual(again['memory_candidates'][0]['candidate_id'],first['candidate_id']);self.assertEqual(len(Gen2Store(path).memory_candidates(goal_id=result['goal_id'])),1);self.assertEqual([e['event_type'] for e in Gen2Store(path).events(result['goal_id'])].count('memory_candidate_proposed'),1)

    def test_model_identity_cannot_approve_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            agent,result=self._complete(Path(d)/'g.db','Remember that I prefer concise weekly robotics updates.');cid=result['memory_candidates'][0]['candidate_id']
            with self.assertRaises(PermissionError):agent.decide_memory_candidate(cid,'approve',actor='model')

if __name__=='__main__':unittest.main()
