import unittest,uuid
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.validation import PlanValidationError,PlanValidator

def base(steps):return PlanProposal(uuid.uuid4().hex,'g',steps,[{'description':'done','verification_method':'all_steps_verified'}],'LOW',0.8,[],'now')
class PlanValidationTests(unittest.TestCase):
    def setUp(self):self.v=PlanValidator({'skill_search'},PolicyEngine())
    def test_duplicate_step_ids_rejected(self):
        s=[PlanProposalStep('x','a',['skill_search'],[],['ok']),PlanProposalStep('x','b',['skill_search'],[],['ok'])]
        with self.assertRaisesRegex(PlanValidationError,'duplicate'):self.v.validate(base(s),subject='user',timestamp='now')
    def test_dependency_cycle_rejected(self):
        s=[PlanProposalStep('a','a',['skill_search'],['b'],['ok']),PlanProposalStep('b','b',['skill_search'],['a'],['ok'])]
        with self.assertRaisesRegex(PlanValidationError,'cycle'):self.v.validate(base(s),subject='user',timestamp='now')
    def test_unresolved_questions_rejected(self):
        p=base([PlanProposalStep('a','a',['skill_search'],[],['ok'])]);p.unresolved_questions=['missing input']
        with self.assertRaisesRegex(PlanValidationError,'unresolved'):self.v.validate(p,subject='user',timestamp='now')
