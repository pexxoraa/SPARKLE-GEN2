import tempfile,unittest
from pathlib import Path
from sparkle_gen2.connectors import ConnectorManager,ConnectorRecord
from sparkle_gen2.context_sources import PersonalContextAssembler
from sparkle_gen2.control_workflows import ObserveActVerifyWorkflow
from sparkle_gen2.devices import DeviceManager,DeviceRecord
from sparkle_gen2.digital_control import BoundedControlGateway
from sparkle_gen2.experiments import ExperimentManager
from sparkle_gen2.image_runtime import ImageGenerationRuntime
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.world_model import WorldModel

class Adapter:
    def health(self):return {'ok':True}
    def invoke(self,op,payload):return {'operation':op,'payload':payload}
    def verify(self,*args):return {'verified':True,'method':'state_reread'}
class ControlAdapter:
    name='control'
    def __call__(self,action,payload):return {'action':action,'payload':payload}
    def verify(self,action,result,before,after):return {'verified':before['action']=='inspect' and after['action']=='inspect' and result['action']==action}
class ImageProvider:
    name='image-test'
    def __call__(self,prompt):return {'artifact':'img-1','prompt':prompt}
class PersonalData:
    def retrieve(self,source,query,limit=5):return {'tool':source+'_tool','output':{'query':query},'verification':{'verified':True}}

class Cycle23Tests(unittest.TestCase):
    def test_context_assembler_covers_personal_goal_device_world_and_connected_sources(self):
        with tempfile.TemporaryDirectory() as d:
            st=Gen2Store(Path(d)/'x.db');world=WorldModel(st);world.observe('proj','project',{'name':'alpha'},{'source':'test'})
            dev=DeviceManager();dev.register(DeviceRecord('phone','mobile','CONNECTED',Adapter(),connection={'kind':'usb'},capabilities=['status'],permissions=['read'],safety_limits={'writes':False},firmware='1.0',last_seen='now'))
            c=ConnectorManager();c.register(ConnectorRecord('calendar',['calendar.read'],'CONNECTED',Adapter()));c.register(ConnectorRecord('gmail',['gmail.read'],'CONNECTED',Adapter()));c.register(ConnectorRecord('outlook',['outlook.read'],'CONNECTED',Adapter()));c.register(ConnectorRecord('files',['files.read'],'CONNECTED',Adapter()))
            out=PersonalContextAssembler(personal_data=PersonalData(),connectors=c,store=st,devices=dev,world=world).gather('alpha project today')
            names={i['source'] for i in out['items']};self.assertTrue({'memory','knowledge','projects','tasks','learning','research','calendar','gmail','outlook','files','devices','world_state'} <= names)
    def test_device_record_exposes_required_safe_metadata(self):
        d=DeviceRecord('esp','iot','BLOCKED',external_dependency='hardware',connection={'transport':'mqtt'},capabilities=['read'],permissions=['read'],safety_limits={'gpio':'typed_only'},firmware='2.0',last_seen='now').public_dict()
        for key in ('device_id','kind','connection','capabilities','status','permissions','safety_limits','firmware','last_seen'):self.assertIn(key,d)
    def test_experiment_tracks_configuration_dataset_code_model_results_metrics_and_links(self):
        m=ExperimentManager();e=m.create('h','m',configuration={'lr':.1},dataset='d1',code_version='abc',model='m1',project_id='p1',research_id='r1');m.record_result(e.experiment_id,{'score':.9},{'accuracy':.9});m.conclude(e.experiment_id,'supported')
        self.assertEqual(e.status,'COMPLETED');self.assertEqual(e.metrics['accuracy'],.9);self.assertEqual(e.project_id,'p1')
    def test_image_artifact_has_goal_project_task_provenance(self):
        r=ImageGenerationRuntime(ImageProvider()).generate('diagram',goal_id='g',project_id='p',task_id='t');self.assertEqual(r['provenance']['goal_id'],'g');self.assertEqual(r['provenance']['provider'],'image-test')
    def test_control_workflow_observes_before_after_and_requires_verification(self):
        adapter=ControlAdapter();g=BoundedControlGateway(adapter,{'inspect','click'});r=ObserveActVerifyWorkflow(g).execute('click',{'x':1},approved=True);self.assertTrue(r['verification']['verified'])
