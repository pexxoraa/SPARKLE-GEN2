"""Bounded projections and owner-checked controls for the Personal OS interface."""
from __future__ import annotations
from .graph import PersonalGraphService
from ..world.dashboard import PersonalOperationsService
from ...core_time import now
from ...domain.models import GoalStatus


class PersonalOSInspector:
    def __init__(self, core):
        self.core = core
        self.store = core.store
        self.graph = getattr(core.agent, 'graph', None) or PersonalGraphService(core.store)
        self._reconciled = set()

    def _owned_goal(self, goal_id, owner):
        goal = self.store.load_goal(goal_id)
        if goal.user_id != owner:raise PermissionError('execution_owner_mismatch')
        return goal

    def execution_list(self, owner='user'):
        goals={g['goal_id']:g for g in self.store.recent_goals(1000) if g.get('user_id','user')==owner}
        rows=[]
        for run in self.store.all_task_runs(500):
            goal=goals.get(run['goal_id'])
            if not goal:continue
            rows.append({'goal_id':goal['goal_id'],'task_run_id':run['task_run_id'],
                         'title':PersonalOperationsService._clean_text(goal.get('normalized_objective','')),
                         'status':goal['status'],'run_status':run['status'],'plan_id':goal.get('plan_id'),
                         'completed_steps':len(run.get('completed_steps',[])), 'pending_steps':len(run.get('pending_steps',[])),
                         'iterations':run.get('iterations',0),'active_runtime_seconds':run.get('active_runtime_seconds',0),
                         'updated_at':run.get('updated_at'),'trace_id':run.get('trace_id')})
        return {'executions':rows[:100]}

    def execution_detail(self, goal_id, owner='user'):
        goal=self._owned_goal(goal_id,owner)
        plan=self.store.load_plan(goal.plan_id).to_dict() if goal.plan_id else None
        run=self.store.load_task_run_for_goal(goal_id)
        return PersonalOperationsService._safe({'goal':goal.to_dict(),'plan':plan,'run':run.to_dict(),
            'criteria':[c.to_dict() for c in self.store.criteria_for_goal(goal_id)],
            'events':self.store.events(goal_id)[-100:], 'traces':self.store.operation_traces(goal_id=goal_id)[-100:]})

    def graph_snapshot(self, owner='user'):
        if owner not in self._reconciled:
            self.graph.reconcile(owner);self._reconciled.add(owner)
        return self.graph.snapshot(owner)

    def control(self, goal_id, action, owner='user'):
        goal=self._owned_goal(goal_id,owner)
        if action not in {'pause','resume','cancel','replan','retry'}:raise ValueError('unknown_execution_control')
        if goal.plan_id:
            method={'resume':'unpause','retry':'resume'}.get(action,action)
            return getattr(self.core.agent,method)(goal_id)
        if action in {'retry','replan','resume'} and self.store.load_task_run_for_goal(goal_id).status!='CAPTURED':
            return self.core.agent.resume(goal_id)
        if action=='cancel':
            goal.status=GoalStatus.CANCELLED;goal.updated_at=now();self.store.save_goal(goal)
            self.core.agent.controls.request(goal_id,'CANCELLED')
            run=self.store.load_task_run_for_goal(goal_id);run.status='CANCELLED';run.updated_at=now();self.store.save_task_run(run)
            self.graph.execution(goal,None,run)
            return {'goal_id':goal_id,'status':'CANCELLED','text':'Saved task cancelled.'}
        raise ValueError('execution_has_no_plan; use Plan with SPARKLE')

    def memory(self, owner='user'):
        return {'candidates':[PersonalOperationsService._safe(c) for c in self.store.memory_candidates() if c.get('owner_user_id','user')==owner][-100:]}

    def memory_decision(self, candidate_id, decision, owner='user', actor='user'):
        candidate=self.store.load_memory_candidate(candidate_id)
        if candidate.get('owner_user_id','user')!=owner:raise PermissionError('memory_owner_mismatch')
        if decision=='reconcile':value=self.core.agent.reconcile_memory_candidate(candidate_id)
        elif decision in {'approve','reject'}:value=self.core.agent.decide_memory_candidate(candidate_id,decision,actor=actor)
        else:raise ValueError('invalid_memory_decision')
        self.graph.memory(self.store.load_memory_candidate(candidate_id))
        return PersonalOperationsService._safe(value.to_dict() if hasattr(value,'to_dict') else value)

    def knowledge(self, owner='user'):
        documents=[]
        for row in self.store.document_records():
            if row.owner_user_id!=owner:continue
            value=row.to_dict()
            documents.append({k:value.get(k) for k in ('document_id','filename','status','classification','created_at','updated_at','source_digest')})
        graph=self.graph_snapshot(owner)
        nodes=[n for n in graph['nodes'] if n['type'] in {'document','result','artifact','knowledge','research','evidence','decision'}]
        return {'documents':documents[-100:],'evidence':nodes[-100:], 'relationships':graph['edges'][-200:]}

    def automations(self, owner='user'):
        items=[]
        service=getattr(self.core.agent,'automation',None)
        for binding in self.store.automation_bindings():
            if binding.owner_user_id!=owner:continue
            item=binding.to_dict()
            if service is not None:
                try:
                    native=service.inspect(binding.automation_id).get('automation',{})
                    item.update({k:native.get(k) for k in ('name','enabled','next_run_at')})
                except (KeyError,ValueError,RuntimeError):item['availability']='UNAVAILABLE'
            items.append(PersonalOperationsService._safe(item))
        return {'automations':items[-100:],'available':service is not None}

    def activity(self, owner='user'):
        owned={g['goal_id'] for g in self.store.recent_goals(1000) if g.get('user_id','user')==owner}
        return {'events':[PersonalOperationsService._safe(x) for x in self.store.recent_events(500) if x.get('goal_id') in owned][:100]}
