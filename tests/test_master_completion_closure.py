import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sparkle_gen2.memory_orchestration import MemoryCandidateAnalyzer, MemoryCandidateService
from sparkle_gen2.models import GoalStatus, CriterionStatus
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.storage import Gen2Store


def completed(goal_id='g1', owner='user', request='Prepare the project report.', artifacts=None):
    goal=SimpleNamespace(goal_id=goal_id,user_id=owner,user_request=request,status=GoalStatus.COMPLETED)
    run=SimpleNamespace(status='COMPLETED',task_run_id='run',trace_id='trace',completed_steps=['verified'],artifacts=artifacts or [])
    criteria=[SimpleNamespace(status=CriterionStatus.SATISFIED)]
    return goal,run,criteria


class CompletionClosureTests(unittest.TestCase):
    def test_verified_artifact_produces_useful_bounded_candidate(self):
        candidates=MemoryCandidateAnalyzer().analyze(*completed(artifacts=['artifact:17','/etc/passwd','artifact:18']))
        self.assertEqual(len(candidates),2)
        self.assertTrue(all(c.source.endswith('artifact_reference') for c in candidates))
        self.assertNotIn('/etc/passwd',str([c.to_dict() for c in candidates]))
        self.assertNotIn('hidden prompt',str(candidates[0].evidence))

    def test_duplicate_suppression_is_cross_goal_and_owner_scoped(self):
        with tempfile.TemporaryDirectory() as d:
            service=MemoryCandidateService(Gen2Store(Path(d)/'g.db'),None,PolicyEngine())
            self.assertEqual(len(service.analyze_completion(*completed(artifacts=['artifact:17']))),1)
            self.assertEqual(service.analyze_completion(*completed('g2',artifacts=['artifact:17'])),[])
            self.assertEqual(len(service.analyze_completion(*completed('g3','second-owner',artifacts=['artifact:17']))),1)

    def test_expired_memory_is_not_approved_or_recalled(self):
        with tempfile.TemporaryDirectory() as d:
            service=MemoryCandidateService(Gen2Store(Path(d)/'g.db'),None,PolicyEngine())
            c=service.analyze_completion(*completed(request='Remember that my goal is finish robotics.'))[0]
            self.assertIsNotNone(c.expires_at)
            c.expires_at=(datetime.now(UTC)-timedelta(seconds=1)).isoformat()
            service.store.save_memory_candidate(c)
            with self.assertRaisesRegex(ValueError,'expired'):service.decide(c.candidate_id,'approve')
            self.assertEqual(service.get(c.candidate_id).state,'EXPIRED')
            c.state='PERSISTED';service.store.save_memory_candidate(c)
            self.assertEqual(service.recall('robotics'),[])

    def test_correction_requires_human_owner_and_remains_a_proposal(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'g.db';service=MemoryCandidateService(Gen2Store(path),None,PolicyEngine())
            c=service.analyze_completion(*completed(request='I prefer weekly summaries.'))[0]
            c.state='PERSISTED';c.memory_id='12';service.store.save_memory_candidate(c)
            with self.assertRaises(PermissionError):service.propose_correction(c.candidate_id,'I prefer daily summaries.',actor='MODEL')
            with self.assertRaises(PermissionError):service.propose_correction(c.candidate_id,'I prefer daily summaries.',owner_user_id='other')
            correction=service.propose_correction(c.candidate_id,'I prefer daily summaries.')
            self.assertEqual(correction.memory_key,c.memory_key)
            self.assertEqual(correction.state,'PROPOSED')
            restored=MemoryCandidateService(Gen2Store(path),None,PolicyEngine())
            self.assertEqual(restored.get(correction.candidate_id).supersedes_candidate_id,c.candidate_id)
            self.assertEqual(restored.recall('weekly')[0]['value'],'I prefer weekly summaries')

    def test_secret_and_unverified_work_do_not_produce_candidates(self):
        goal,run,criteria=completed(request='Remember my password is example.',artifacts=['artifact:12'])
        self.assertEqual(MemoryCandidateAnalyzer().analyze(goal,run,criteria),[])
        goal,run,criteria=completed(artifacts=['artifact:12']);run.status='FAILED'
        self.assertEqual(MemoryCandidateAnalyzer().analyze(goal,run,criteria),[])
