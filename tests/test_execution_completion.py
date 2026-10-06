import tempfile
import threading
import unittest
import uuid
from pathlib import Path

from sparkle.system import SparkleSystem
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.gen1 import LocalGen1Gateway, ToolObservation
from sparkle_gen2.models import PlanProposal, PlanProposalStep, StepStatus
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.conversations import ConversationService
from sparkle_gen2.sessions import SessionService


def proposal(two=False, write=False):
    cap='memory_write' if write else 'calculator'
    steps=[PlanProposalStep('one', 'First bounded action', [cap], [], ['verified'], {} if write else {'expression':'2+2'}, 30, 1)]
    if two:steps.append(PlanProposalStep('two','Second bounded action',['calculator'],['one'],['verified'],{'expression':'3+3'},30,1))
    return PlanProposal(uuid.uuid4().hex,'x',steps,[{'description':'independently verified','verification_method':'all_steps_verified'}],'MEDIUM' if write else 'LOW',1,[],'test')


class Gateway:
    def __init__(self, fail=False, hook=None):self.calls=[];self.fail=fail;self.hook=hook
    def health(self):return {'tools':['calculator','memory_write']}
    def retrieve_context(self,*args):return {'source':'test','rendered':''}
    def invoke(self,tool,args):
        self.calls.append((tool,args.copy()))
        if self.hook:self.hook()
        if self.fail:self.fail=False;return ToolObservation(False,tool,{'error':'temporary failure'},{'verified':False})
        return ToolObservation(True,tool,{'calls':len(self.calls)},{'verified':True,'method':'independent state reread'})


class CompletionTests(unittest.TestCase):
    def test_natural_intention_executes_real_gen1_and_persists_graph(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'g.db';store=Gen2Store(db)
            agent=PersonalAgent(store,LocalGen1Gateway(SparkleSystem()),planner=StaticPlanner(proposal()))
            service=ConversationService(store,SessionService(store),agent)
            result=service.send('I want to calculate 2+2.')
            self.assertEqual(result['result']['status'],'COMPLETED')
            graph=Gen2Store(db).graph_snapshot('user')
            self.assertEqual({n['type'] for n in graph['nodes']},{'person','agent','tool','goal','task','plan','execution','step','result'})
            self.assertTrue(any(e['type']=='produces' for e in graph['edges']))
            self.assertTrue(all(e['from']!=e['to'] for e in graph['edges']))
            self.assertEqual(Gen2Store(db).graph_snapshot('other')['nodes'],[])

    def test_production_auto_retry_completes_without_another_message(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.db');gateway=Gateway(fail=True)
            agent=PersonalAgent(store,gateway,planner=StaticPlanner(proposal()),auto_retry=True)
            result=agent.start('Calculate')
            self.assertEqual(result['status'],'COMPLETED')
            run=store.load_task_run_for_goal(result['goal_id'])
            self.assertEqual(run.iterations,2);self.assertEqual(run.failed_steps,[])
            self.assertEqual(run.recovery_history[0]['action'],'RETRY')

    def test_pause_survives_restart_and_resume_does_not_repeat_verified_step(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'g.db';store=Gen2Store(db);gateway=Gateway()
            agent=PersonalAgent(store,gateway,planner=StaticPlanner(proposal(two=True)))
            def hook():
                if len(gateway.calls)==1:agent.pause(store.recent_goals(1)[0]['goal_id'])
            gateway.hook=hook
            result=agent.start('Two actions');gid=result['goal_id']
            self.assertEqual(store.load_task_run_for_goal(gid).status,'PAUSED')
            restarted=PersonalAgent(Gen2Store(db),gateway,planner=StaticPlanner(proposal(two=True)))
            restarted.resume(gid);self.assertEqual(len(gateway.calls),1)
            self.assertEqual(restarted.unpause(gid)['status'],'COMPLETED')
            self.assertEqual(len(gateway.calls),2)

    def test_cancel_during_action_prevents_next_action(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.db');gateway=Gateway()
            agent=PersonalAgent(store,gateway,planner=StaticPlanner(proposal(two=True)))
            gateway.hook=lambda:agent.cancel(store.recent_goals(1)[0]['goal_id'])
            result=agent.start('Two actions')
            self.assertEqual(result['status'],'CANCELLED');self.assertEqual(len(gateway.calls),1)
            self.assertEqual(agent.resume(result['goal_id'])['status'],'CANCELLED')

    def test_iteration_budget_is_not_reset_by_restart(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'g.db';gateway=Gateway(fail=True)
            result=PersonalAgent(Gen2Store(db),gateway,planner=StaticPlanner(proposal()),max_iterations=1).start('Calculate')
            agent=PersonalAgent(Gen2Store(db),gateway,planner=StaticPlanner(proposal()),max_iterations=1)
            self.assertEqual(agent.resume(result['goal_id'])['status'],'BLOCKED')
            self.assertEqual(len(gateway.calls),1)
            self.assertEqual(agent.store.load_task_run_for_goal(result['goal_id']).status,'BUDGET_EXHAUSTED')

    def test_concurrent_resume_never_duplicates_action(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.db');entered=threading.Event();release=threading.Event()
            gateway=Gateway(hook=lambda:(entered.set(),release.wait(5)))
            agent=PersonalAgent(store,gateway,planner=StaticPlanner(proposal()))
            results=[];worker=threading.Thread(target=lambda:results.append(agent.start('Calculate')))
            worker.start()
            try:
                self.assertTrue(entered.wait(5));gid=store.recent_goals(1)[0]['goal_id']
                busy=PersonalAgent(store,gateway,planner=StaticPlanner(proposal())).resume(gid)
                self.assertEqual(busy['status'],'WAITING');self.assertEqual(len(gateway.calls),1)
            finally:release.set();worker.join(5)
            self.assertFalse(worker.is_alive());self.assertEqual(results[0]['status'],'COMPLETED')

    def test_interrupted_write_is_blocked_before_reexecution(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.db');gateway=Gateway();agent=PersonalAgent(store,gateway,planner=StaticPlanner(proposal(write=True)))
            result=agent.start('Write');agent.decide_approval(result['approvals'][0],'approve')
            goal=store.load_goal(result['goal_id']);plan=store.load_plan(goal.plan_id);plan.steps[0].status=StepStatus.EXECUTING;store.save_plan(plan)
            result=PersonalAgent(store,gateway,planner=StaticPlanner(proposal(write=True))).resume(goal.goal_id)
            self.assertEqual(result['status'],'BLOCKED');self.assertEqual(gateway.calls,[])
            self.assertEqual(store.load_task_run_for_goal(goal.goal_id).status,'INTERRUPTED_ACTION')

    def test_out_of_order_dependencies_execute_in_topological_order(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.db');gateway=Gateway();p=proposal(two=True);p.steps.reverse()
            result=PersonalAgent(store,gateway,planner=StaticPlanner(p)).start('Two actions')
            self.assertEqual(result['status'],'COMPLETED')
            self.assertEqual([args['expression'] for _,args in gateway.calls],['2+2','3+3'])
