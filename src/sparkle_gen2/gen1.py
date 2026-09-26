from __future__ import annotations
import hashlib,json,uuid
from pathlib import Path
from dataclasses import dataclass
from typing import Any,Protocol

@dataclass(slots=True)
class ToolObservation:
    ok:bool; tool:str; output:dict[str,Any]; verification:dict[str,Any]
    requires_approval:bool=False; approval_id:str|None=None

class _AuthorizedToolProxy:
    def __init__(self,base,authorization):self.base=base;self.authorization=authorization
    def definitions(self,allowed=None):
        if allowed is None:return self.base.definitions()
        return self.base.definitions(self.authorization.visible_tools(set(allowed)))
    def execute(self,name,arguments,*,allowed=None):
        if allowed is None:raise PermissionError('delegated tool execution requires specialist allowlist')
        authorized=self.authorization.authorize(name,arguments,set(allowed));output=self.base.execute(name,authorized,allowed=set(allowed));self.authorization.observe(name,authorized,output);return output
    def status(self):return self.base.status()

class Gen1Gateway(Protocol):
    def retrieve_context(self,request:str,requirements:list[str])->dict[str,Any]: ...
    def invoke(self,tool:str,arguments:dict[str,Any])->ToolObservation: ...
    def health(self)->dict[str,Any]: ...
    def plan(self,goal:dict[str,Any],context:dict[str,Any],available_capabilities:list[str])->dict[str,Any]: ...
    def approval_status(self,approval_id:str,tool:str)->dict[str,Any]: ...

class LocalGen1Gateway:
    def __init__(self,system=None):
        if system is None:
            from sparkle.system import SparkleSystem
            from .model_manager import build_gen2_model_registry
            registry=build_gen2_model_registry(path=Path(__file__).with_name('nemotron_models.json'))
            active=registry.record(registry.active_id)
            if active.provider!='nvidia' or 'nemotron' not in active.model_id.lower() or not active.enabled:
                raise RuntimeError('nemotron_only_registry_violation')
            system=SparkleSystem(model_registry=registry)
        self.system=system
        self._external_workspace_worker=None
        try:
            from .protected_secrets import build_protected_external_worker
            self._external_workspace_worker=build_protected_external_worker(self.system.workspaces.root)
        except Exception:
            self._external_workspace_worker=None
        self._strict_workspace_worker=None
        try:
            from .workspace_isolation import build_strict_workspace_worker
            self._strict_workspace_worker=build_strict_workspace_worker(self.system.workspaces.root)
        except Exception:
            self._strict_workspace_worker=None
        from .model_manager import CapabilityRouter,ModelCapabilityManager
        self.model_manager=ModelCapabilityManager(registry=self.system.models,fallback_allowed=False);self.capability_router=CapabilityRouter(self.model_manager)
    def health(self):
        models=[]
        for rid,record in self.system.models._records.items():
            hs=self.system.models.health.status(rid);cfg=record.config;secret_refs=cfg.get('secret_refs',[]);configured=(rid in self.system.models._injected_ids or not secret_refs or any(self.system.models.secrets.status(secret_refs).values()))
            models.append({'record_id':rid,'provider':record.provider,'model':record.model_id,'roles':sorted(record.roles),'capabilities':sorted(cfg.get('capabilities',record.roles)),'modalities':list(record.modalities),'input_modalities':list(cfg.get('input_modalities',record.modalities)),'output_modalities':list(cfg.get('output_modalities',['text'])),'supports_tools':bool(cfg.get('supports_tools',False) or 'tool_use' in record.roles),'enabled':record.enabled,'active':rid==self.system.models.active_id,'configured':configured,'health':hs['state'],'health_reason':hs.get('reason'),'allow_fallback':bool(cfg.get('allow_fallback',False)),'context_window':cfg.get('context_window'),'max_output_tokens':cfg.get('max_output_tokens'),'latency_class':cfg.get('latency_class','balanced')})
        agents=self.system.agents.list() if hasattr(self.system,'agents') else []
        definitions=[]
        for d in self.system.tools.definitions():
            parameters=d.parameters
            if d.name=='workspace_test':
                # Gen-2 owns authorization. The model proposes only the workspace identity;
                # the trusted wrapper injects Gen-1's transport-level approved flag after
                # exact persisted human approval.
                source=dict(d.parameters or {})
                props=dict(source.get('properties') or {})
                parameters={
                    'type':'object',
                    'properties':{'project_name':dict(props.get('project_name') or {'type':'string'})},
                    'required':['project_name'],
                    'additionalProperties':False,
                }
            definitions.append({'name':d.name,'description':d.description,'parameters':parameters})
        worker_status={'configured':False};strict_status={'configured':False}
        if self._external_workspace_worker is not None:
            try:
                raw=self._external_workspace_worker.status();worker_status={k:raw.get(k) for k in ('configured','enabled','endpoint_https_valid','worker_identity_configured','https_required','explicit_approval_required')}
            except Exception:worker_status={'configured':False}
        if self._strict_workspace_worker is not None:
            try:
                raw=self._strict_workspace_worker.status();executor=dict(raw.get('executor') or {});strict_status={'configured':bool(raw.get('configured')),'enabled':bool(raw.get('enabled')),'worker_identity_configured':bool(raw.get('worker_identity_configured')),'explicit_approval_required':bool(raw.get('explicit_approval_required')),'isolation_verified':bool(raw.get('isolation_verified')),'profile':executor.get('isolation_profile'),'filesystem_isolation':bool(executor.get('filesystem_isolation')),'network_isolation':bool(executor.get('network_isolation')),'resource_limits':bool(executor.get('resource_limits'))}
            except Exception:strict_status={'configured':False}
        return {'available':True,'tools':sorted(self.system.tools.names),'tool_definitions':definitions,'models':models,'agents':agents,'boundary':'SparkleSystem/ToolRegistry','external_workspace_worker':worker_status,'strict_workspace_worker':strict_status}
    def retrieve_context(self,request,requirements):
        bundle=self.system.context.build(request)
        return {'requirements':list(requirements),'rendered':bundle.render()[:6000],'source':'gen1-context'}
    def plan(self,goal,context,available_capabilities):
        from sparkle.contracts import Message,ModelRequest

        available=set(available_capabilities)

        # Gen-2 supplies the authoritative planner-visible tool schemas.
        # This includes Gen-2-owned tools such as operations_snapshot.
        supplied_definitions=context.get('tool_schemas')

        if isinstance(supplied_definitions,dict):
            tool_definitions=[]
            for name,definition in supplied_definitions.items():
                if name not in available or not isinstance(definition,dict):
                    continue
                tool_definitions.append({
                    'name':name,
                    'description':str(definition.get('description','')),
                    'parameters':dict(definition.get('parameters') or {}),
                })
        else:
            # Backward-compatible fallback for direct gateway callers/tests
            # that do not provide Gen-2 planner schemas.
            tool_definitions=[]
            tool_registry=getattr(self.system,'tools',None)
            if tool_registry is not None:
                for d in tool_registry.definitions():
                    if d.name not in available:
                        continue

                    parameters=d.parameters

                    # Gen-2 owns authorization for workspace_test. The planner
                    # proposes only the project identity; the trusted wrapper
                    # supplies the transport-level approval flag after approval.
                    if d.name=='workspace_test':
                        source=dict(d.parameters or {})
                        props=dict(source.get('properties') or {})
                        parameters={
                            'type':'object',
                            'properties':{
                                'project_name':dict(
                                    props.get('project_name') or {'type':'string'}
                                )
                            },
                            'required':['project_name'],
                            'additionalProperties':False,
                        }

                    tool_definitions.append({
                        'name':d.name,
                        'description':d.description,
                        'parameters':parameters,
                    })

        schema={
            'goal_id':goal['goal_id'],
            'steps':[{
                'step_id':'step-1',
                'objective':'bounded action',
                'required_capabilities':['one exact capability/tool name'],
                'depends_on':[],
                'success_criteria':['observable result'],
                'arguments':{},
                'timeout_seconds':30,
                'retry_limit':1,
            }],
            'success_criteria':[{
                'description':'goal result verified',
                'verification_method':'all_steps_verified',
            }],
            'risk':'LOW',
            'confidence':0.0,
            'unresolved_questions':[],
        }

        prompt=(
            'Create a minimal executable plan for this goal. '
            'Return ONLY one JSON object, with no markdown and no commentary. '

            'Use only tools present in AVAILABLE_TOOL_DEFINITIONS. '
            'required_capabilities MUST contain exactly one allowed '
            'capability/tool name for each step. '

            'Do NOT emit any field named preferred_tool. '
            'The executable tool selection is derived deterministically by '
            'Gen-2 from required_capabilities after planning. '

            'Every step.arguments MUST be a JSON object conforming to the '
            'selected tool parameters schema. '
            'Every schema-required argument MUST be present and non-empty. '
            'When additionalProperties is false, do not add undeclared arguments. '

            'NEVER invent connector IDs, notification IDs, device IDs, project '
            'IDs, artifact IDs, or other opaque identifiers. '
            'Only use identifiers explicitly present in GOAL or '
            'RELEVANT_CONTEXT, or produced by an earlier verified step. '

            'If a required identifier is not known yet, do not call that tool '
            'with an empty or invented value. Prefer a suitable preceding '
            'read-only list/discovery/inspection tool when one is available. '

            'For operations_snapshot specifically: the optional day argument '
            'is a calendar date in YYYY-MM-DD form. '
            'When the request means current/today/now and no explicit calendar '
            'date is supplied, OMIT day entirely. '
            'NEVER use natural-language values such as today, tomorrow, '
            'yesterday, current, or now for day. '

            'For a goal asking for current system status, operational status, '
            'or a concrete next action, prefer an available bounded aggregate '
            'read-only status/snapshot tool when its description matches that '
            'purpose. Use the resulting grounded next_action rather than '
            'inventing a recommendation from raw subsystem state. '

            'For example, if operations_snapshot is available and the goal '
            'asks for current system status plus one concrete next action, '
            'use operations_snapshot with arguments {} unless the goal '
            'explicitly supplies an ISO calendar date. '

            'Dependencies must reference earlier or existing step IDs. '
            'Each step must request exactly one capability/tool. '

            'The model proposes actions only; it cannot grant permission, '
            'approve, execute, verify, or declare completion. '

            f'GOAL={json.dumps({k:goal[k] for k in ("goal_id","user_request","constraints","deadline")},ensure_ascii=False)}\\n'
            f'AVAILABLE_CAPABILITIES={json.dumps(sorted(available),ensure_ascii=False)}\\n'
            f'AVAILABLE_TOOL_DEFINITIONS={json.dumps(tool_definitions,ensure_ascii=False,separators=(",",":"))}\\n'
            f'RELEVANT_CONTEXT={json.dumps(str(context.get("rendered",""))[:6000],ensure_ascii=False)}\\n'
            f'OUTPUT_SHAPE={json.dumps(schema,ensure_ascii=False,separators=(",",":"))}'
        )

        request=ModelRequest(
            messages=[Message(role='user',content=prompt)],
            system='You are SPARKLE Gen-2 planner. Produce strict JSON only.',
            max_output_tokens=1024,
            temperature=0.0,
            thinking=False,
            metadata={
                'operation':'gen2_plan',
                'required_capabilities':['planning','reasoning'],
            },
        )

        architecture_route=None
        if getattr(self,'capability_router',None) is not None:
            architecture_route=self.capability_router.require(
                ['planning','reasoning'],
                input_modalities=['text'],
                output_modalities=['text'],
            )

        decision,response=self.system.model_router.complete(
            request,
            'reasoning',
            modalities={'text'},
            latency_policy='deep',
            max_timeout_seconds=120,
        )

        if (
            architecture_route is not None
            and getattr(
                decision,
                'record_id',
                architecture_route.selected.record_id
            ) != architecture_route.selected.record_id
        ):
            raise RuntimeError('gen2_capability_route_mismatch')

        if (
            decision.provider!='nvidia'
            or 'nemotron' not in decision.model.lower()
            or decision.fallback
        ):
            raise RuntimeError('nemotron_only_route_violation')

        text=response.text.strip()

        try:
            raw=json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError('planner_invalid_json') from exc

        if not isinstance(raw,dict):
            raise RuntimeError('planner_output_not_object')

        raw['goal_id']=goal['goal_id']

        # preferred_tool is a Gen-2-derived execution field, not planner input.
        # Reject accidental emission explicitly rather than allowing a later
        # dataclass TypeError.
        for step in raw.get('steps',[]):
            if isinstance(step,dict) and 'preferred_tool' in step:
                raise RuntimeError(
                    'planner_derived_field_forbidden:preferred_tool'
                )

        prov={
            'request_id':response.provider_request_id or uuid.uuid4().hex,
            'provider':decision.provider,
            'model':decision.model,
            'capability':decision.capability,
            'requested_capabilities':['planning','reasoning'],
            'selection_reason':decision.selection_reason,
            'health':decision.health,
            'trace_id':None,
            'fallback':decision.fallback,
        }

        return {'proposal':raw,'provenance':prov}

    def approval_status(self,approval_id,tool):
        if tool!='memory_write' or not hasattr(self.system,'memory_review'):
            return {'status':'UNKNOWN','verified':False,'reason':'unsupported_approval_type'}
        for status in ('pending','approved','rejected'):
            try: rows=self.system.memory_review.list(limit=100,status=status)
            except Exception as exc:return {'status':'UNKNOWN','verified':False,'reason':type(exc).__name__}
            for row in rows:
                if row.get('id')==approval_id:
                    state=row.get('status',status).upper();memory_id=row.get('memory_id')
                    verified=state=='APPROVED' and memory_id is not None
                    return {'status':state,'verified':verified,'memory_id':memory_id,'source':'gen1_memory_review'}
        return {'status':'UNKNOWN','verified':False,'reason':'approval_not_found'}
    def specialist_catalog(self):
        if not hasattr(self.system,'agents'):return []
        return list(self.system.agents.list())
    def specialist_limits(self):
        orchestrator=getattr(self.system,'orchestrator',None)
        if orchestrator is None:return {}
        return {'max_specialists':int(orchestrator.max_specialists),'max_tool_calls':int(orchestrator.max_tool_calls),'max_rounds':int(orchestrator.max_tool_rounds),'max_runtime_seconds':int(orchestrator.max_workflow_seconds),'cancellation':'pre_start_only','restart_resume':False}
    def delegate_specialists(self,objective,specialists,*,user_id,input_source,authorization=None):
        orchestrator=getattr(self.system,'orchestrator',None)
        if orchestrator is None:raise RuntimeError('specialist_orchestrator_unavailable')
        if authorization is not None:
            authorization.runtime=self
            base=orchestrator;proxy=_AuthorizedToolProxy(self.system.tools,authorization)
            orchestrator=type(base)(models=base.models,agents=base.agents,agent_router=base.agent_router,context=base.context,tools=proxy,traces=base.traces,max_tool_rounds=base.max_tool_rounds,max_tool_calls=base.max_tool_calls,max_specialists=base.max_specialists,max_workflow_seconds=base.max_workflow_seconds)
        result=orchestrator.run_multi(str(objective),agent_names=list(specialists),user_id=user_id,input_source=input_source)
        traces=[r for r in self.system.traces.recent(limit=100) if r.get('input_source')==input_source]
        requested=set(specialists);specialist_rows=[r for r in traces if r.get('agent') in requested]
        synthesis=[r for r in traces if r.get('agent')=='personal'];catalog={x['name']:x for x in self.specialist_catalog()}
        by_name={r.get('agent'):r for r in reversed(specialist_rows)}
        specialist_results=[];evidence=[];pending=[];failed=[]
        for name in specialists:
            row=by_name.get(name)
            if row is None:
                failed.append({'specialist':name,'reason':'missing_persistent_trace'});continue
            metadata=dict(row.get('execution_metadata') or {});proposal_ids=list(metadata.get('memory_proposal_ids') or []);requested_tools=list(metadata.get('tool_calls_requested') or []);allowed_tools=set(catalog.get(name,{}).get('tools',[]));unauthorized=sorted(set(requested_tools)-allowed_tools)
            if proposal_ids:pending.extend({'specialist':name,'approval_id':x,'tool':'memory_write'} for x in proposal_ids)
            if unauthorized:failed.append({'specialist':name,'reason':'unauthorized_tool_request:'+','.join(unauthorized)})
            specialist_results.append({'specialist':name,'status':row.get('status'),'text':str(row.get('result_summary') or '')[:500],'tools':list(row.get('tools') or []),'requested_tools':requested_tools,'trace_id':row.get('trace_id'),'provider':row.get('provider'),'model':row.get('model'),'execution_metadata':metadata})
            evidence.append({'specialist':name,'trace_id':row.get('trace_id'),'status':row.get('status'),'tools':list(row.get('tools') or [])})
            if row.get('status')!='success':failed.append({'specialist':name,'reason':row.get('error_type') or row.get('status')})
        synth=next((r for r in synthesis if r.get('trace_id')==result.trace_id),synthesis[0] if synthesis else None)
        if len(specialists)>1:
            if synth is None:failed.append({'specialist':'personal','reason':'missing_synthesis_trace'})
            elif synth.get('status')!='success':failed.append({'specialist':'personal','reason':synth.get('error_type') or synth.get('status')})
        elif result.agent!=specialists[0]:failed.append({'specialist':specialists[0],'reason':'single_specialist_result_identity_mismatch'})
        auth_provenance={} if authorization is None else authorization.provenance()
        if authorization is not None and getattr(authorization.request,'authorized_action',None) is not None:
            action_tool=str(authorization.request.authorized_action.get('tool',''));checks=[x for x in auth_provenance.get('execution_verifications',[]) if x.get('tool')==action_tool]
            if len(checks)!=1 or checks[0].get('verification',{}).get('verified') is not True:failed.append({'specialist':specialists[0] if specialists else 'unknown','reason':'authorized_action_independent_verification_missing_or_failed'})
            else:evidence.append({'authorized_action':action_tool,'verification':checks[0]['verification']})
        if pending:status='WAITING_APPROVAL';verified=False
        elif failed:status='FAILED';verified=False
        else:status='COMPLETED';verified=True
        return {'status':status,'specialist_results':specialist_results,'findings':result.text,'artifacts':[],'evidence':evidence,'confidence':1.0 if verified else 0.0,'unresolved_items':[x['reason'] for x in failed]+(['pending Gen-1 approval'] if pending else []),'provenance':{'gen1_final_trace_id':result.trace_id,'specialist_trace_ids':[x.get('trace_id') for x in specialist_results],'provider':result.provider,'model':result.model,'input_source':input_source,'user_id':user_id,'pending_approvals':pending,'authorization':auth_provenance},'verification':{'verified':verified,'method':'Gen-1 persistent specialist traces plus independent authorized-action verification','pending_approvals':pending,'specialist_count':len(specialist_results),'authorized_action_verification':auth_provenance.get('execution_verifications',[])},'failure':None if not failed else {'category':'SPECIALIST_FAILURE','items':failed}}

    def artifacts(self,limit=50):
        return self.system.artifacts.list(limit=max(1,min(int(limit),100)))
    def artifact_content(self,artifact_id):
        import hashlib
        if type(artifact_id) is not int or artifact_id<1:raise ValueError('invalid_artifact_id')
        row=next((r for r in self.system.artifacts.list(limit=100) if r.get('artifact_id')==artifact_id),None)
        if row is None:raise KeyError(artifact_id)
        root=self.system.artifacts.artifact_root.resolve();target=(root/str(row['artifact_name'])).resolve()
        if root not in target.parents or not target.is_file() or target.is_symlink():raise RuntimeError('artifact_path_invalid')
        content=target.read_bytes();digest=hashlib.sha256(content).hexdigest()
        if digest!=row.get('artifact_sha256'):raise RuntimeError('artifact_digest_mismatch')
        return {'artifact_id':artifact_id,'name':target.name,'sha256':digest,'content':content}
    def package_source_identity(self,project_name):
        project=self.system.artifacts._project_root(str(project_name));files,metadata,total=self.system.artifacts._source_files(project);source_value={'project_name':str(project_name),'files':metadata,'source_bytes':total};digest=hashlib.sha256(self.system.artifacts._canonical_json(source_value)).hexdigest();return {'project_name':str(project_name),'source_digest':digest,'file_count':len(metadata),'source_bytes':total}
    def validate_delegated_action_preconditions(self,tool,arguments):
        if tool=='workspace_scaffold':
            project=str(arguments.get('project_name',''));root=self.system.workspaces.root.resolve();target=(root/project).resolve()
            if target.parent!=root:raise PermissionError('delegated workspace escapes applications root')
            if target.exists():raise FileExistsError('delegated workspace scaffold requires a new project')
            return True
        if tool=='workspace_verify':
            verifier=self.system.development;project=verifier._project_root(str(arguments.get('project_name','')))
            for check in list(arguments.get('checks') or []):
                target,relative=verifier._target(project,str(check.get('path','')));check_type=str(check.get('type',''))
                suffix=target.suffix.lower()
                if check_type=='python_compile' and suffix!='.py':raise ValueError(f'python_compile requires a .py file: {relative}')
                if check_type=='javascript_syntax' and suffix not in {'.js','.mjs','.cjs'}:raise ValueError(f'javascript_syntax requires a JavaScript file: {relative}')
                if check_type=='json_parse' and suffix!='.json':raise ValueError(f'json_parse requires a .json file: {relative}')
            return True
        if tool=='workspace_package':
            self.system.artifacts._project_root(str(arguments.get('project_name','')))
            return True
        return True
    def verify_delegated_action(self,tool,arguments,output):
        if tool=='workspace_scaffold':
            project=str(arguments.get('project_name',''));files=dict(arguments.get('files') or {});root=self.system.workspaces.root.resolve();project_root=(root/project).resolve()
            expected={str(Path(path).as_posix()):hashlib.sha256(content.encode('utf-8')).hexdigest() for path,content in files.items()}
            if project_root.parent!=root or not project_root.is_dir() or project_root.is_symlink():return {'verified':False,'method':'exact approved workspace manifest filesystem reread','reason':'workspace missing or unsafe'}
            actual={}
            try:
                for target in project_root.rglob('*'):
                    if target.is_symlink():return {'verified':False,'method':'exact approved workspace manifest filesystem reread','reason':'symlink found'}
                    if target.is_file():actual[target.relative_to(project_root).as_posix()]=hashlib.sha256(target.read_bytes()).hexdigest()
            except OSError:return {'verified':False,'method':'exact approved workspace manifest filesystem reread','reason':'filesystem reread failed'}
            record=next((r for r in self.system.workspaces.list(limit=100) if r.get('build_id')==output.get('build_id') and r.get('project_name')==project),None)
            verified=record is not None and actual==expected
            return {'verified':verified,'method':'exact approved workspace manifest filesystem reread','project_name':project,'expected_files':sorted(expected),'actual_files':sorted(actual),'manifest_digest':hashlib.sha256(json.dumps(expected,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
        if tool=='workspace_verify':
            project=str(arguments.get('project_name',''));expected=[{'type':str(c.get('type','')),'path':str(c.get('path',''))} for c in list(arguments.get('checks') or [])];vid=output.get('verification_id')
            row=next((r for r in self.system.development.list(limit=100) if r.get('verification_id')==vid and r.get('project_name')==project),None)
            if row is None:return {'verified':False,'method':'exact approved workspace verification persisted-state reread','reason':'verification run missing','verification_id':vid}
            persisted=[{'type':str(c.get('type','')),'path':str(c.get('path',''))} for c in list(row.get('checks') or [])]
            returned=[{'type':str(c.get('type','')),'path':str(c.get('path',''))} for c in list(output.get('checks') or [])]
            statuses=[str(c.get('status','')) for c in list(row.get('checks') or [])]
            verified=(persisted==expected and returned==expected and row.get('status')=='passed' and output.get('status')=='passed' and int(row.get('failed',-1))==0 and int(output.get('failed',-1))==0 and int(row.get('passed',-1))==len(expected) and int(output.get('passed',-1))==len(expected) and statuses==['passed']*len(expected))
            return {'verified':verified,'method':'exact approved workspace verification persisted-state reread','verification_id':vid,'project_name':project,'expected_checks':expected,'persisted_checks':persisted,'returned_checks':returned,'persisted_status':row.get('status'),'returned_status':output.get('status'),'passed':row.get('passed'),'failed':row.get('failed')}
        if tool=='workspace_package':
            project=str(arguments.get('project_name',''));aid=output.get('artifact_id');row=next((r for r in self.system.artifacts.list(limit=100) if r.get('artifact_id')==aid and r.get('project_name')==project),None)
            if row is None:return {'verified':False,'method':'exact approved workspace package artifact reread','reason':'artifact record missing','artifact_id':aid}
            root=self.system.artifacts.artifact_root.resolve();target=(root/str(row.get('artifact_name',''))).resolve();project_root=self.system.artifacts._project_root(project)
            try:
                files,metadata,total=self.system.artifacts._source_files(project_root);source_value={'project_name':project,'files':metadata,'source_bytes':total};source_digest=hashlib.sha256(self.system.artifacts._canonical_json(source_value)).hexdigest();artifact_bytes=target.read_bytes() if root in target.parents and target.is_file() and not target.is_symlink() else b'';artifact_digest=hashlib.sha256(artifact_bytes).hexdigest() if artifact_bytes else ''
            except Exception:return {'verified':False,'method':'exact approved workspace package artifact reread','reason':'independent artifact/source reread failed','artifact_id':aid}
            manifest=dict(row.get('manifest') or {});verified=(source_digest==row.get('source_digest')==output.get('source_digest') and artifact_digest==row.get('artifact_sha256')==output.get('artifact_sha256') and manifest.get('project_name')==project and manifest.get('source_digest')==source_digest and manifest.get('archive_format')=='zip-stored' and int(row.get('file_count',-1))==len(metadata) and int(row.get('source_bytes',-1))==total)
            return {'verified':verified,'method':'exact approved workspace package artifact reread','artifact_id':aid,'project_name':project,'artifact_name':row.get('artifact_name'),'artifact_sha256':artifact_digest,'source_digest':source_digest,'archive_format':manifest.get('archive_format'),'file_count':len(metadata),'source_bytes':total}
        return {'verified':True,'method':'delegated action uses existing independent boundary'}

    def _attest_workspace_isolation(self,output):
        try:
            from .protected_secrets import protected_worker_runtime_status
            health=protected_worker_runtime_status()
        except Exception:
            health={'reachable':False,'ready':False}
        claims=dict(output.get('sandbox_claims') or {}) if isinstance(output,dict) else {}
        expected_id=str(getattr(self._external_workspace_worker,'expected_worker_id','') or '')
        expected_canaries={'host_filesystem_read','host_filesystem_write','workspace_escape','secret_environment','prohibited_network','host_process_access','artifact_modification'}
        canaries=health.get('canaries') if isinstance(health.get('canaries'),dict) else {}
        verified=bool(
            output.get('response_verified')
            and expected_id
            and claims.get('worker_id')==expected_id==health.get('worker_id')
            and claims.get('filesystem_isolation') is True
            and claims.get('network_isolation') is True
            and claims.get('ephemeral') is True
            and claims.get('resource_limits') is True
            and health.get('reachable') is True
            and health.get('ready') is True
            and health.get('direct_tls') is True
            and health.get('credentials_exposed') is False
            and health.get('executor_mode')=='bubblewrap'
            and health.get('preflight_passed') is True
            and health.get('filesystem_isolation') is True
            and health.get('network_isolation') is True
            and health.get('ephemeral_workspace') is True
            and health.get('resource_limits') is True
            and health.get('unsafe_process_mode') is False
            and health.get('hostile_canaries_passed') is True
            and health.get('preflight_canary_evidence_complete') is True
            and health.get('isolation_profile')=='SPARKLE-WORKER-BUBBLEWRAP/1'
            and set(canaries)==expected_canaries
            and all(canaries.values())
        )
        evidence={
            'verified':verified,
            'method':'signed worker result + TLS worker health + Bubblewrap hostile-canary attestation',
            'worker_identity_match':bool(expected_id and claims.get('worker_id')==expected_id==health.get('worker_id')),
            'filesystem_isolation':bool(claims.get('filesystem_isolation') and health.get('filesystem_isolation')),
            'network_isolation':bool(claims.get('network_isolation') and health.get('network_isolation')),
            'ephemeral_workspace':bool(claims.get('ephemeral') and health.get('ephemeral_workspace')),
            'resource_limits':bool(claims.get('resource_limits') and health.get('resource_limits')),
            'process_isolation':bool(canaries.get('host_process_access')),
            'environment_sanitization':bool(canaries.get('secret_environment')),
            'credential_isolation':bool(health.get('credentials_exposed') is False and canaries.get('secret_environment')),
            'host_filesystem_read_blocked':bool(canaries.get('host_filesystem_read')),
            'host_filesystem_write_blocked':bool(canaries.get('host_filesystem_write')),
            'workspace_escape_blocked':bool(canaries.get('workspace_escape')),
            'direct_tls':bool(health.get('direct_tls')),
            'hostile_canaries_passed':bool(health.get('hostile_canaries_passed') and canaries and all(canaries.values())),
            'isolation_profile':health.get('isolation_profile'),
        }
        return evidence

    def _attest_strict_workspace_isolation(self,output):
        worker=self._strict_workspace_worker
        if worker is None:return {'verified':False,'method':'strict workspace worker unavailable'}
        try:health=worker.status()
        except Exception:return {'verified':False,'method':'strict workspace worker health unavailable'}
        executor=dict(health.get('executor') or {});claims=dict(output.get('sandbox_claims') or {}) if isinstance(output,dict) else {};canaries=dict(executor.get('canaries') or {});expected={'host_filesystem_read','host_filesystem_write','workspace_escape','secret_environment','prohibited_network','host_process_access','artifact_modification'}
        worker_id=str(output.get('worker_id') or '');identity_ok=bool(worker_id.startswith('sparkle-gen2-strict-') and worker_id==health.get('worker_id')==claims.get('worker_id'))
        verified=bool(output.get('response_verified') and identity_ok and claims.get('filesystem_isolation') is True and claims.get('network_isolation') is True and claims.get('ephemeral') is True and claims.get('resource_limits') is True and health.get('configured') is True and health.get('credentials_exposed') is False and executor.get('mode')=='bubblewrap' and executor.get('preflight_passed') is True and executor.get('filesystem_isolation') is True and executor.get('network_isolation') is True and executor.get('ephemeral_workspace') is True and executor.get('resource_limits') is True and executor.get('unsafe_process_mode') is False and executor.get('hostile_canaries_passed') is True and executor.get('preflight_canary_evidence_complete') is True and executor.get('isolation_profile')=='SPARKLE-GEN2-WORKSPACE-STRICT/1' and set(canaries)==expected and all(canaries.values()))
        return {'verified':verified,'method':'strict Bubblewrap status reread + hostile-canary attestation','worker_identity_match':identity_ok,'filesystem_isolation':bool(claims.get('filesystem_isolation') and executor.get('filesystem_isolation')),'network_isolation':bool(claims.get('network_isolation') and executor.get('network_isolation')),'ephemeral_workspace':bool(claims.get('ephemeral') and executor.get('ephemeral_workspace')),'resource_limits':bool(claims.get('resource_limits') and executor.get('resource_limits')),'process_isolation':bool(canaries.get('host_process_access')),'environment_sanitization':bool(canaries.get('secret_environment')),'credential_isolation':bool(health.get('credentials_exposed') is False and canaries.get('secret_environment')),'host_filesystem_read_blocked':bool(canaries.get('host_filesystem_read')),'host_filesystem_write_blocked':bool(canaries.get('host_filesystem_write')),'workspace_escape_blocked':bool(canaries.get('workspace_escape')),'hostile_canaries_passed':bool(canaries and all(canaries.values())),'direct_tls':False,'local_fixed_boundary':True,'isolation_profile':executor.get('isolation_profile')}

    def invoke(self,tool,arguments):
        if tool=='workspace_test':
            worker=self._strict_workspace_worker
            if worker is None:return ToolObservation(False,tool,{'error':'strict isolated workspace worker unavailable'},{'verified':False,'reason':'strict_isolated_workspace_worker_unavailable'})
            try:
                if set(arguments)!={'project_name','approved'} or arguments.get('approved') is not True:raise PermissionError('workspace test requires exact approved scope')
                output=worker.run(str(arguments['project_name']))
                output_limited=bool(output.get('output_limited'));isolation=self._attest_strict_workspace_isolation(output)
                output=dict(output)|{'isolation_verified':bool(isolation.get('verified')),'isolation_evidence':isolation}
                verification=self._verify_observation(tool,arguments,output)
                return ToolObservation(bool(verification.get('verified')),tool,output,verification)
            except Exception as exc:
                return ToolObservation(False,tool,{'error':'isolated workspace test failed','error_type':type(exc).__name__},{'verified':False,'reason':'isolated_worker_execution_failed'})
        if tool not in self.system.tools.names:
            return ToolObservation(False,tool,{'error':'tool unavailable'},{'verified':False,'reason':'not_registered'})
        try: output=self.system.tools.execute(tool,arguments,allowed={tool})
        except Exception as exc:
            return ToolObservation(False,tool,{'error':str(exc),'error_type':type(exc).__name__},{'verified':False,'reason':'execution_failed'})
        if not isinstance(output,dict):output={'value':output}
        if tool=='memory_write' and output.get('status')=='pending':
            pid=output.get('proposal_id'); verified=False
            if isinstance(pid,str) and hasattr(self.system,'memory_review'):
                verified=any(r.get('id')==pid for r in self.system.memory_review.list(limit=100,status='pending'))
            return ToolObservation(True,tool,output,{'verified':verified,'method':'re-read pending memory proposal'},True,pid)
        verification=self._verify_observation(tool,arguments,output)
        return ToolObservation(True,tool,output,verification)

    def _verify_observation(self,tool,arguments,output):
        if tool=='workspace_scaffold':
            project=str(arguments.get('project_name',''));build_id=output.get('build_id')
            record=next((r for r in self.system.workspaces.list(limit=100) if r.get('build_id')==build_id and r.get('project_name')==project),None)
            root=(self.system.workspaces.root/project).resolve();verified=record is not None and root.is_dir()
            for item in output.get('files',[]) if verified else []:
                target=(root/str(item.get('path',''))).resolve()
                if root not in target.parents or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=item.get('sha256'):
                    verified=False;break
            return {'verified':verified,'method':'re-read workspace build record and file digests'}
        if tool=='workspace_verify':
            vid=output.get('verification_id');project=output.get('project_name')
            row=next((r for r in self.system.development.list(limit=100) if r.get('verification_id')==vid and r.get('project_name')==project),None)
            verified=bool(row and row.get('status')=='passed' and row.get('failed')==0 and output.get('status')=='passed')
            return {'verified':verified,'method':'re-read persisted Gen-1 verification run','verification_id':vid}
        if tool=='workspace_test':
            project=output.get('project_name');external_id=output.get('external_test_run_id');strict=str(output.get('worker_id') or '').startswith('sparkle-gen2-strict-')
            worker=getattr(self,'_strict_workspace_worker',None) if strict else getattr(self,'_external_workspace_worker',None)
            if external_id is not None and worker is not None:
                row=next((r for r in worker.list(limit=100) if r.get('external_test_run_id')==external_id and r.get('project_name')==project),None);isolation=dict(output.get('isolation_evidence') or {})
                if strict:
                    verified=bool(row and row.get('status')=='passed' and row.get('returncode')==0 and not row.get('timed_out') and not output.get('output_limited') and row.get('response_verified') and output.get('response_verified') and output.get('isolation_verified') and isolation.get('verified') and dict(row.get('sandbox_claims') or {})==dict(output.get('sandbox_claims') or {}))
                    return {'verified':verified,'method':'re-read strict worker run + independent Bubblewrap isolation attestation','external_test_run_id':external_id,'response_verified':bool(output.get('response_verified')),'output_limited':bool(output.get('output_limited')),'isolation_verified':bool(output.get('isolation_verified')),'filesystem_isolation':bool(isolation.get('filesystem_isolation')),'network_isolation':bool(isolation.get('network_isolation')),'process_isolation':bool(isolation.get('process_isolation')),'environment_sanitization':bool(isolation.get('environment_sanitization')),'credential_isolation':bool(isolation.get('credential_isolation')),'resource_limits':bool(isolation.get('resource_limits')),'host_filesystem_read_blocked':bool(isolation.get('host_filesystem_read_blocked')),'host_filesystem_write_blocked':bool(isolation.get('host_filesystem_write_blocked')),'workspace_escape_blocked':bool(isolation.get('workspace_escape_blocked')),'hostile_canaries_passed':bool(isolation.get('hostile_canaries_passed')),'direct_tls':False,'local_fixed_boundary':True,'isolation_profile':isolation.get('isolation_profile'),'worker_id':output.get('worker_id')}
                verified=bool(row and row.get('status')=='passed' and row.get('returncode')==0 and not row.get('timed_out') and row.get('response_verified') and output.get('response_verified') and output.get('isolation_verified'))
                return {'verified':verified,'method':'legacy external worker result reread; strict isolation evidence required for production acceptance','external_test_run_id':external_id,'response_verified':bool(output.get('response_verified')),'isolation_verified':bool(output.get('isolation_verified'))}
            tid=output.get('test_run_id');row=next((r for r in self.system.workspace_tests.list(limit=100) if r.get('test_run_id')==tid and r.get('project_name')==project),None)
            verified=bool(row and row.get('status')=='passed' and row.get('returncode')==0 and not row.get('timed_out'))
            return {'verified':verified,'method':'re-read persisted Gen-1 test run','test_run_id':tid}
        if tool=='workspace_package':
            aid=output.get('artifact_id');project=output.get('project_name');digest=output.get('artifact_sha256')
            row=next((r for r in self.system.artifacts.list(limit=100) if r.get('artifact_id')==aid and r.get('project_name')==project and r.get('artifact_sha256')==digest),None)
            verified=row is not None
            if verified:
                root=self.system.artifacts.artifact_root.resolve();target=(root/str(row.get('artifact_name',''))).resolve()
                verified=root in target.parents and target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest()==digest
            return {'verified':verified,'method':'re-read artifact registry and package digest','artifact_id':aid}
        if tool=='agent_install':
            name=output.get('name');capability=output.get('capability');tools=sorted(output.get('tools',[]))
            persisted=[]
            if hasattr(self.system,'generated_agents'):persisted=self.system.generated_agents.load()
            verified=any(getattr(spec,'name',None)==name and getattr(spec,'capability',None)==capability and sorted(getattr(spec,'tools',[]))==tools for spec in persisted)
            return {'verified':verified,'method':'re-read generated-agent persistent store','agent':name}
        return {'verified':True,'method':'Gen-1 read-only tool result contract; no state change'}
