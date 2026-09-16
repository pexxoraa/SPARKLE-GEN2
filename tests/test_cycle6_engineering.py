import unittest
from sparkle_gen2.digital_control import BoundedControlGateway
from sparkle_gen2.experiments import ExperimentManager
from sparkle_gen2.self_improvement import ControlledImprovementPipeline

class Cycle6EngineeringTests(unittest.TestCase):
    def test_digital_control_denies_shell_and_unapproved_writes(self):
        g=BoundedControlGateway(lambda a,p:{'observed':a},{'inspect','click'})
        with self.assertRaises(PermissionError):g.invoke('shell',{})
        with self.assertRaises(PermissionError):g.invoke('click',{})
        self.assertEqual(g.invoke('click',{},approved=True)['observed'],'click')
    def test_experiment_requires_evidence_before_conclusion(self):
        m=ExperimentManager();e=m.create('A improves B','bounded A/B test')
        with self.assertRaises(ValueError):m.conclude(e.experiment_id,'works')
        m.observe(e.experiment_id,{'metric':1});self.assertEqual(m.conclude(e.experiment_id,'supported').status,'COMPLETED')
    def test_self_improvement_cannot_self_approve_or_skip_tests(self):
        p=ControlledImprovementPipeline();c=p.propose('new.tool','typed design')
        with self.assertRaises(PermissionError):p.approve(c.candidate_id,'model')
        with self.assertRaises(ValueError):p.approve(c.candidate_id,'human')
        p.record_tests(c.candidate_id,True);p.review(c.candidate_id,True);p.approve(c.candidate_id,'human')
        self.assertEqual(p.install(c.candidate_id).status,'INSTALLED')

if __name__=='__main__':unittest.main()
