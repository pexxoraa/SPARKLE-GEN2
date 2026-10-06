"""Persistent owner-scoped links between Personal OS and execution entities."""
from __future__ import annotations
from ...core_time import now
from ..world.dashboard import PersonalOperationsService


class PersonalGraphService:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def node(identity, kind, title, status, owner):
        return {'id': str(identity), 'type': kind, 'title': PersonalOperationsService._clean_text(title)[:300],
                'status': str(status), 'owner_user_id': owner, 'updated_at': now()}

    @staticmethod
    def edge(source, target, relation, owner):
        return {'id': f'{source}|{relation}|{target}', 'from': source, 'to': target,
                'type': relation, 'owner_user_id': owner, 'updated_at': now()}

    def execution(self, goal, plan=None, run=None):
        owner = goal.user_id
        nodes = [self.node(goal.goal_id, 'goal', goal.normalized_objective, goal.status.value, owner)]
        person='person:'+owner
        nodes.append(self.node(person,'person','Workspace owner','ACTIVE',owner))
        edges = [self.edge(person,goal.goal_id,'owns',owner)]
        task = 'task:' + goal.goal_id
        nodes.append(self.node(task, 'task', goal.normalized_objective, goal.status.value, owner))
        edges.append(self.edge(goal.goal_id, task, 'contains', owner))
        if plan:
            nodes.append(self.node(plan.plan_id, 'plan', goal.normalized_objective, goal.status.value, owner))
            edges.append(self.edge(goal.goal_id, plan.plan_id, 'planned_by', owner))
        if run:
            nodes.append(self.node(run.task_run_id, 'execution', goal.normalized_objective, run.status, owner))
            edges.append(self.edge(task, run.task_run_id, 'executed_by', owner))
            if plan:
                edges.append(self.edge(plan.plan_id, run.task_run_id, 'executed_by', owner))
                for step in plan.steps:
                    sid = plan.plan_id + ':' + step.step_id
                    nodes.append(self.node(sid, 'step', step.description, step.status.value, owner))
                    edges.append(self.edge(plan.plan_id, sid, 'contains', owner))
                    edges.append(self.edge(run.task_run_id, sid, 'executes', owner))
                    tool='tool:'+step.preferred_tool;agent='agent:'+step.preferred_agent
                    nodes.extend([self.node(tool,'tool',step.preferred_tool,'REGISTERED',owner),self.node(agent,'agent',step.preferred_agent,'REGISTERED',owner)])
                    edges.extend([self.edge(sid,tool,'uses',owner),self.edge(sid,agent,'coordinated_by',owner)])
                    for dependency in step.dependencies:
                        edges.append(self.edge(sid, plan.plan_id + ':' + dependency, 'depends_on', owner))
                    if step.result:
                        rid = 'result:' + run.task_run_id + ':' + step.step_id
                        verified = (step.result.get('verification') or {}).get('verified') is True
                        nodes.append(self.node(rid, 'result', step.description, 'VERIFIED' if verified else 'UNVERIFIED', owner))
                        edges.append(self.edge(sid, rid, 'produces', owner))
                        output = step.result.get('output') or {}
                        if isinstance(output, dict) and output.get('artifact_id'):
                            aid = str(output['artifact_id'])
                            nodes.append(self.node(aid, 'artifact', output.get('artifact_name') or step.description, 'VERIFIED' if verified else 'UNVERIFIED', owner))
                            edges.append(self.edge(rid, aid, 'produces', owner))
        for field, relation in (('project_id', 'part_of'), ('parent_goal_id', 'part_of'), ('learning_plan_id', 'supports')):
            target = (goal.metadata or {}).get(field) or (getattr(goal, field, None) if field == 'parent_goal_id' else None)
            if target and self._owned(str(target), owner):
                edges.append(self.edge(goal.goal_id, str(target), relation, owner))
        for node in nodes:
            if node['type'] not in {'person','agent','tool'}:node['goal_id']=goal.goal_id
        self.store.save_graph(nodes, edges)

    def _owned(self, identity, owner):
        try:
            return self.store.load_goal(identity).user_id == owner
        except KeyError:
            pass
        try:
            return self.store.load_os_record(identity).get('owner_user_id') == owner
        except KeyError:
            pass
        try:
            return self.store.load_learning_plan(identity).owner_user_id == owner
        except KeyError:
            return False

    def record(self, record):
        owner = record.get('owner_user_id', 'user')
        rid = record.get('record_id') or record.get('plan_id') or record.get('document_id') or record.get('experiment_id')
        if not rid:
            return
        kind = record.get('record_type') or ('learning' if record.get('plan_id') else 'experiment' if record.get('experiment_id') else 'document')
        nodes = [self.node(rid, kind, record.get('title') or record.get('subject') or record.get('filename') or record.get('hypothesis') or rid, record.get('status', 'ACTIVE'), owner)]
        edges = []
        for field, relation in (('goal_id', 'supports'), ('project_id', 'part_of'), ('learning_plan_id', 'developed_by'),('research_id','investigates')):
            target = record.get(field) or (record.get('metadata') or {}).get(field)
            if target and self._owned(str(target), owner):
                edges.append(self.edge(str(rid), str(target), relation, owner))
        if kind=='learning':
            for unit in record.get('units',[]):
                identity=str(rid)+':'+str(unit['unit_id'])
                nodes.append(self.node(identity,'learning_unit',unit['title'],unit['status'],owner))
                edges.append(self.edge(str(rid),identity,'contains',owner))
            for assessment in record.get('assessments',[]):
                identity=str(assessment['assessment_id'])
                nodes.append(self.node(identity,'evidence','Human-reviewed learning assessment','RECORDED',owner))
                edges.append(self.edge(identity,str(rid)+':'+str(assessment['unit_id']),'assesses',owner))
        if kind=='experiment' and record.get('results'):
            evidence='evidence:'+str(rid)
            nodes.append(self.node(evidence,'evidence','Recorded experiment result',record.get('verification_state','UNVERIFIED'),owner))
            edges.append(self.edge(str(rid),evidence,'produces',owner))
            if record.get('conclusion'):
                knowledge='knowledge:'+str(rid)
                nodes.append(self.node(knowledge,'knowledge',record['conclusion'],record.get('verification_state','UNVERIFIED'),owner))
                edges.append(self.edge(evidence,knowledge,'supports',owner))
        self.store.save_graph(nodes, edges)

    def memory(self,candidate):
        owner=candidate.owner_user_id
        if not self._owned(candidate.goal_id,owner):return
        nodes=[self.node(candidate.candidate_id,'memory',candidate.category,candidate.state,owner)]
        edges=[self.edge(candidate.goal_id,candidate.candidate_id,'proposes',owner)]
        if candidate.state=='PERSISTED':
            identity='knowledge:memory:'+candidate.candidate_id
            nodes.append(self.node(identity,'decision' if candidate.category=='decisions' else 'knowledge',candidate.category,'PERSISTED',owner))
            edges.append(self.edge(candidate.candidate_id,identity,'supports',owner))
        for node in nodes:node['goal_id']=candidate.goal_id
        self.store.save_graph(nodes,edges)

    def reconcile(self, owner='user'):
        for row in self.store.recent_goals(1000):
            if row.get('user_id', 'user') != owner:
                continue
            goal = self.store.load_goal(row['goal_id'])
            plan = self.store.load_plan(goal.plan_id) if goal.plan_id else None
            try:
                run = self.store.load_task_run_for_goal(goal.goal_id)
            except KeyError:
                run = None
            self.execution(goal, plan, run)
        for row in self.store.os_records(owner_user_id=owner, limit=1000):
            self.record(row)
        for plan in self.store.learning_plans(owner_user_id=owner, limit=1000):
            self.record(plan.to_dict())
        for row in self.store.document_records()[:1000]:
            if row.owner_user_id==owner:self.record(row.to_dict())
        for row in self.store.experiments():
            if row.get('owner_user_id','user')==owner:self.record(row)
        for candidate in self.store.memory_candidates():
            if candidate.owner_user_id==owner:self.memory(candidate)

    def snapshot(self, owner='user', limit=500):
        return self.store.graph_snapshot(owner, limit=max(1, min(int(limit), 1000)))
