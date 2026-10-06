import json,tempfile,unittest
from pathlib import Path
from sparkle.registry import ModelRegistry
from sparkle_gen2.model_manager import ModelCapabilityManager
from sparkle.contracts import ModelRequest,Message

class ModelSelectionCompletionTests(unittest.TestCase):
    def manager(self,**policy):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        record={'id':'selected','provider':'nvidia','model_id':'nvidia/test-contract','adapter':'nvidia_chat_completions','roles':['reasoning','planning'],'modalities':['text'],'input_modalities':['text'],'output_modalities':['text'],'enabled':True,'allow_fallback':False,'latency_class':'fast'}
        record.update(policy)
        path=Path(directory.name)/'models.json'
        path.write_text(json.dumps({'active_model':'selected','models':[record],'routing':{'default':'selected','reasoning':'selected','planning':'selected'}}))
        return ModelCapabilityManager(registry=ModelRegistry(path=path))

    def test_cost_location_complexity_latency_and_privacy_filter_real_registry(self):
        manager=self.manager(execution_location='local',privacy_classifications=['PUBLIC','PERSONAL','SENSITIVE'],cost_per_million_tokens=2,max_task_complexity='complex')
        constraints={'execution_location':'local','classification':'SENSITIVE','max_cost_per_million_tokens':2,'task_complexity':'complex','latency_class':'fast'}
        self.assertEqual(manager.route(['planning','reasoning'],constraints=constraints).selected.record_id,'selected')
        for field,value in [('execution_location','remote'),('classification','SECRET'),('max_cost_per_million_tokens',1),('latency_class','deep')]:
            with self.subTest(field=field):
                self.assertIsNone(manager.route(['reasoning'],constraints=constraints|{field:value}).selected)

    def test_unknown_cost_and_complexity_cannot_satisfy_explicit_limits(self):
        manager=self.manager()
        self.assertIsNotNone(manager.route(['reasoning']).selected)
        for constraints in ({'max_cost_per_million_tokens':10},{'task_complexity':'simple'},{'execution_location':'local'},{'classification':'SENSITIVE'}):
            with self.subTest(constraints=constraints):
                self.assertIsNone(manager.route(['reasoning'],constraints=constraints).selected)

    def test_request_constraints_block_before_native_adapter_or_network(self):
        manager=self.manager(execution_location='remote')
        request=ModelRequest(messages=[Message('user','Bounded test')],metadata={'model_constraints':{'execution_location':'local'}})
        with self.assertRaisesRegex(RuntimeError,'model_capability_unavailable'):
            manager.complete(request,['reasoning'])

    def test_invalid_constraints_are_rejected_without_echoing_values(self):
        manager=self.manager()
        for constraints in ({'max_cost_per_million_tokens':float('nan')},{'max_cost_per_million_tokens':True},{'task_complexity':'arbitrary'},{'execution_location':'untrusted'},{'unexpected':'private-context'}):
            with self.subTest(keys=list(constraints)):
                with self.assertRaises(ValueError) as error:manager.route(['reasoning'],constraints=constraints)
                self.assertNotIn('private-context',str(error.exception))

    def test_invalid_registry_policy_cannot_advertise_availability(self):
        for metadata in ({'cost_per_million_tokens':-1},{'privacy_classifications':['arbitrary']},{'execution_location':'untrusted'},{'max_task_complexity':'arbitrary'}):
            with self.subTest(keys=list(metadata)):
                with self.assertRaises(ValueError):self.manager(**metadata).inventory()

    def test_malformed_selection_values_fail_as_clean_validation_errors(self):
        from sparkle_gen2.infrastructure.providers.model_selection import selection_metadata
        manager=self.manager()
        for field in ('execution_location','classification','task_complexity','latency_class'):
            for value in (['private-field-value'],{'private':'private-field-value'}):
                with self.subTest(constraint=field,kind=type(value).__name__):
                    with self.assertRaises(ValueError) as error:manager.route(['reasoning'],constraints={field:value})
                    self.assertNotIn('private-field-value',str(error.exception))
        for metadata in ({'execution_location':['private-field-value']},{'max_task_complexity':{'private':'private-field-value'}},{'privacy_classifications':[{'private':'private-field-value'}]},['private-field-value']):
            with self.subTest(metadata_kind=type(metadata).__name__):
                with self.assertRaises(ValueError) as error:selection_metadata(metadata)
                self.assertNotIn('private-field-value',str(error.exception))

    def test_native_usage_dto_is_counted_only_when_provider_reports_it(self):
        from types import SimpleNamespace
        from dataclasses import asdict
        from sparkle.contracts import ModelResponse,TokenUsage
        from sparkle_gen2.gen1 import LocalGen1Gateway
        from sparkle_gen2.models import PlanProposal,PlanProposalStep
        proposal=PlanProposal('proposal','goal',[PlanProposalStep('one','Calculate',['calculator'],[],['observed'],{'expression':'2+2'})],[{'description':'observed','verification_method':'all_steps_verified'}],'LOW',1,[],'test')
        response=ModelResponse(json.dumps(asdict(proposal)),'test-model','test-provider','stop',usage=TokenUsage(11,7),usage_reported=True)
        class Router:
            def complete(self,request,*args,**kwargs):
                self.request=request
                return SimpleNamespace(provider='test-provider',model='test-model',capability='reasoning',selection_reason='configured',health='HEALTHY',fallback=False),response
        router=Router();gateway=LocalGen1Gateway.__new__(LocalGen1Gateway);gateway.system=SimpleNamespace(model_router=router)
        goal={'goal_id':'goal','user_request':'Calculate 2+2','constraints':[],'deadline':None}
        observed=gateway.plan(goal,{'rendered':''},['calculator'])
        self.assertEqual(observed['provenance']['resource_usage'],{'input_tokens':11,'output_tokens':7})
        response.usage_reported=False
        self.assertNotIn('resource_usage',gateway.plan(goal,{'rendered':''},['calculator'])['provenance'])

    def test_strict_parser_diagnostic_excludes_private_model_values(self):
        from types import SimpleNamespace
        from sparkle_gen2.planner import Gen1PlannerModel,PlannerError
        from sparkle_gen2.models import Goal
        raw={'goal_id':'goal','steps':[{'step_id':'one','objective':'Calculate','required_capabilities':['calculator'],'depends_on':[],'success_criteria':['observed'],'arguments':{'expression':'2+2'},'preferred_agent':'private-model-value'}],'success_criteria':[{'description':'observed','verification_method':'all_steps_verified'}],'risk':'LOW','confidence':1,'unresolved_questions':[]}
        gateway=SimpleNamespace(plan=lambda *args:{'proposal':raw,'provenance':{}})
        with self.assertRaises(PlannerError) as observed:Gen1PlannerModel(gateway).propose(Goal('goal','Calculate','Calculate'),{},['calculator'])
        self.assertEqual(observed.exception.schema_component,'step')
        self.assertEqual(observed.exception.unexpected_fields,['preferred_agent'])
        self.assertNotIn('private-model-value',str(observed.exception))
        from sparkle_gen2.application.execution.lifecycle_service import ExecutionLifecycleService
        error=RuntimeError('private diagnostic')
        error.schema_component='step';error.unexpected_fields=['preferred_agent','private-model-field',{'private':'payload'}]
        detail=ExecutionLifecycleService.planning_error(error)
        self.assertEqual(detail['unexpected_fields'],['preferred_agent'])
        self.assertNotIn('private-model-field',str(detail));self.assertNotIn('payload',str(detail))
        error.category={'private':'payload'};error.schema_component=['private-field']
        detail=ExecutionLifecycleService.planning_error(error)
        self.assertEqual(detail['error_category'],'planning_failure');self.assertNotIn('payload',str(detail))
        self.assertNotIn('schema_component',detail)

    def test_malformed_plan_collections_remain_safe_planner_failures(self):
        from types import SimpleNamespace
        from sparkle_gen2.planner import Gen1PlannerModel,PlannerError
        from sparkle_gen2.models import Goal
        for steps in (None,1,{'private-model-value':'x'},'private-model-value'):
            with self.subTest(kind=type(steps).__name__):
                raw={'steps':steps,'success_criteria':[{'description':'observed','verification_method':'all_steps_verified'}],'risk':'LOW','confidence':1}
                gateway=SimpleNamespace(plan=lambda *args:{'proposal':raw,'provenance':{}})
                with self.assertRaises(PlannerError) as observed:Gen1PlannerModel(gateway).propose(Goal('goal','Calculate','Calculate'),{},['calculator'])
                self.assertEqual(observed.exception.schema_component,'step')
                self.assertEqual(observed.exception.unexpected_fields,[])
                self.assertNotIn('private-model-value',str(observed.exception))

    def test_unavailable_primary_uses_only_explicitly_allowed_fallback(self):
        from sparkle.model import ModelAdapter
        from sparkle.contracts import ModelResponse
        from sparkle.secrets import SecretResolver
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        base={'provider':'nvidia','adapter':'nvidia_chat_completions','roles':['reasoning'],'modalities':['text'],'enabled':True,'input_modalities':['text'],'output_modalities':['text']}
        records=[base|{'id':'primary-contract','model_id':'nvidia/primary-contract','allow_fallback':False,'secret_refs':['UNCONFIGURED_PRIMARY_CONTRACT_KEY']},base|{'id':'alternate-contract','model_id':'nvidia/alternate-contract','allow_fallback':True}]
        path=Path(directory.name)/'models.json';path.write_text(json.dumps({'active_model':'primary-contract','models':records,'routing':{'default':'primary-contract','reasoning':'primary-contract'}}))
        registry=ModelRegistry(path=path,secrets=SecretResolver({}))
        class Alternative(ModelAdapter):
            provider='test-provider';model_id='test-alternative';calls=0
            def complete(self,request):
                self.calls+=1;return ModelResponse('bounded response',self.model_id,self.provider,'stop')
            def health(self):return {'configured':True}
        alternative=Alternative();registry.inject('alternate-contract',alternative)
        manager=ModelCapabilityManager(registry=registry,fallback_allowed=True)
        result=manager.complete(ModelRequest(messages=[Message('user','Bounded request')]),['reasoning'])
        self.assertTrue(result['provenance']['fallback']);self.assertEqual(result['route']['selected']['record_id'],'alternate-contract');self.assertEqual(alternative.calls,1)
        manager.fallback_allowed=False
        with self.assertRaisesRegex(RuntimeError,'model_capability_unavailable'):manager.complete(ModelRequest(messages=[Message('user','Bounded request')]),['reasoning'])
        self.assertEqual(alternative.calls,1)
