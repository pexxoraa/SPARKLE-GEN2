"""Link Personal OS records to real authorized execution instead of independent CRUD."""
from __future__ import annotations
from .graph import PersonalGraphService
from ...core_time import now


class PersonalOSWorkflowService:
    def __init__(self, core):self.core=core;self.store=core.store;self.graph=PersonalGraphService(core.store)

    def plan(self, record_type, record_id, *, owner_user_id='user'):
        kind={'projects':'project','skills':'skill','goals':'goal','tasks':'task'}.get(record_type,record_type)
        if kind in {'project','research','skill'}:
            row=self.store.load_os_record(record_id)
            if row.get('owner_user_id')!=owner_user_id:raise PermissionError('os_item_owner_mismatch')
            if row.get('record_type')!=kind:raise ValueError('os_record_type_mismatch')
        elif kind in {'goal','task'}:
            goal=self.store.load_goal(record_id)
            if goal.user_id!=owner_user_id:raise PermissionError('os_item_owner_mismatch')
            row=goal.to_dict()
        elif kind=='learning':
            plan=self.store.load_learning_plan(record_id)
            if plan.owner_user_id!=owner_user_id:raise PermissionError('os_item_owner_mismatch')
            row=plan.to_dict()
        else:raise ValueError('unsupported_os_item_type')
        title=str(row.get('title') or row.get('name') or row.get('subject') or row.get('normalized_objective') or row.get('objective') or record_id)
        context=str(row.get('description') or row.get('question') or row.get('hypothesis') or row.get('objective') or '')
        command='Plan and execute the next bounded step for '+title+'.'
        if context:command+=' Context: '+context[:700]
        result=self.core.agent.start(command,user_id=owner_user_id)
        execution=self.store.load_goal(result['goal_id'])
        execution.metadata=dict(execution.metadata or {})|{'source_record_id':record_id,'source_record_type':kind}
        if kind in {'goal','task'}:
            execution.parent_goal_id=record_id
            goal.metadata=dict(goal.metadata or {})|{'execution_goal_id':execution.goal_id}
            goal.updated_at=now();self.store.save_goal(goal);self.graph.execution(goal)
        elif kind=='project':execution.metadata['project_id']=record_id
        elif kind=='learning':execution.metadata['learning_plan_id']=record_id
        self.store.save_goal(execution)
        if kind in {'project','research','skill'}:
            row=self.core.update_manual_record(record_id,{'metadata':{'execution_goal_id':execution.goal_id,'last_execution_status':result.get('status','PLANNED')}},owner_user_id=owner_user_id)
            self.graph.record(row)
        plan=self.store.load_plan(execution.plan_id) if execution.plan_id else None
        try:run=self.store.load_task_run_for_goal(execution.goal_id)
        except KeyError:run=None
        self.graph.execution(execution,plan,run)
        return {'status':result.get('status'),'goal_id':execution.goal_id,'task_run_id':result.get('task_run_id'),
                'text':result.get('text'),'linked_record':row,'planning_result':result}
