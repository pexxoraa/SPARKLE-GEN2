import tempfile,unittest
from pathlib import Path
from sparkle_gen2.cross_domain import CrossDomainCoordinator,DomainRequirement
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.world_model import WorldModel

class Cycle15Tests(unittest.TestCase):
    def test_world_model_persists_nodes_edges_freshness_and_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.sqlite3');w=WorldModel(store)
            w.observe('p','project',{'status':'active'},{'source':'gen1','record':'p1'});w.observe('t','task',{'status':'open'})
            edge=w.relate('p','contains','t',{'source':'project_tasks'});self.assertTrue(edge.edge_id)
            recovered=WorldModel(Gen2Store(Path(d)/'g.sqlite3'));snap=recovered.snapshot()
            self.assertEqual(len(snap['nodes']),2);self.assertEqual(len(snap['edges']),1);self.assertGreaterEqual(snap['nodes'][0]['age_seconds'],0)
            self.assertEqual(recovered.nodes['p'].provenance['source'],'gen1')
            self.assertEqual(recovered.neighbors('p',relation='contains')[0]['node']['node_id'],'t')
            self.assertEqual(recovered.fresh_nodes(kind='project',max_age_seconds=60)[0]['node_id'],'p')
    def test_cross_domain_completion_requires_independent_verification(self):
        good=lambda q:{'output':{'q':q},'verification':{'verified':True,'method':'state_read'}}
        bad=lambda q:{'output':{},'verification':{'verified':False}}
        c=CrossDomainCoordinator({'projects':good,'tasks':good,'email':bad})
        ok=c.execute([DomainRequirement('projects','alpha'),DomainRequirement('tasks','alpha')]);self.assertEqual(ok['status'],'COMPLETE')
        blocked=c.execute([DomainRequirement('projects','alpha'),DomainRequirement('email','important')]);self.assertEqual(blocked['status'],'BLOCKED');self.assertEqual(blocked['failures'][0]['reason'],'unverified')
    def test_cross_domain_bounds_and_missing_required_domain_fail_closed(self):
        c=CrossDomainCoordinator({'memory':lambda q:{'verification':{'verified':True},'output':[]}},max_domains=2)
        self.assertEqual(c.execute([DomainRequirement('calendar','today')])['status'],'BLOCKED')
        with self.assertRaises(ValueError):c.execute([DomainRequirement('memory','a'),DomainRequirement('memory','b'),DomainRequirement('memory','c')])
if __name__=='__main__':unittest.main()
