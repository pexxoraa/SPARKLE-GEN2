from __future__ import annotations
import json,sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from .models import *

class Gen2Store:
    def __init__(self,path:str|Path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self._init()
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path);db.row_factory=sqlite3.Row
        try:
            yield db;db.commit()
        except Exception:
            db.rollback();raise
        finally:
            db.close()
    def _init(self):
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS goals(goal_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS plans(plan_id TEXT PRIMARY KEY,goal_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS plan_proposals(proposal_id TEXT PRIMARY KEY,goal_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS task_runs(task_run_id TEXT PRIMARY KEY,goal_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS permissions(permission_id TEXT PRIMARY KEY,goal_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS risks(risk_id TEXT PRIMARY KEY,goal_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS approvals(approval_id TEXT PRIMARY KEY,goal_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS criteria(criterion_id TEXT PRIMARY KEY,goal_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS model_provenance(request_id TEXT PRIMARY KEY,goal_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(session_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS background_tasks(background_id TEXT PRIMARY KEY,goal_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS proactive_events(event_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS automation_bindings(automation_id INTEGER PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS world_nodes(node_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS world_edges(edge_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS perception_observations(observation_id TEXT PRIMARY KEY,robot_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_perception_robot ON perception_observations(robot_id);
            CREATE TABLE IF NOT EXISTS notifications(notification_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notification_decisions(decision_id TEXT PRIMARY KEY,candidate_id TEXT NOT NULL UNIQUE,owner_user_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_notification_decisions_owner ON notification_decisions(owner_user_id);
            CREATE TABLE IF NOT EXISTS notification_channel_states(channel_state_id TEXT PRIMARY KEY,owner_user_id TEXT NOT NULL,channel TEXT NOT NULL,device_id TEXT,payload TEXT NOT NULL,UNIQUE(owner_user_id,channel,device_id));
            CREATE INDEX IF NOT EXISTS idx_notification_channels_owner ON notification_channel_states(owner_user_id,channel);
            CREATE TABLE IF NOT EXISTS notification_delivery_attempts(attempt_id TEXT PRIMARY KEY,decision_id TEXT NOT NULL,notification_id TEXT NOT NULL,owner_user_id TEXT NOT NULL,channel TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_notification_delivery_owner ON notification_delivery_attempts(owner_user_id,notification_id);
            CREATE INDEX IF NOT EXISTS idx_notification_delivery_decision ON notification_delivery_attempts(decision_id);
            CREATE TABLE IF NOT EXISTS daily_briefs(brief_id TEXT PRIMARY KEY,owner_user_id TEXT NOT NULL,day TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_daily_briefs_owner_day ON daily_briefs(owner_user_id,day);
            CREATE TABLE IF NOT EXISTS improvement_candidates(candidate_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS rollback_records(rollback_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memory_candidates(candidate_id TEXT PRIMARY KEY,goal_id TEXT NOT NULL,memory_id TEXT,payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_memory_candidates_goal ON memory_candidates(goal_id);
            CREATE INDEX IF NOT EXISTS idx_memory_candidates_memory ON memory_candidates(memory_id);
            CREATE TABLE IF NOT EXISTS delegations(request_id TEXT PRIMARY KEY,goal_id TEXT NOT NULL,task_run_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_delegations_goal ON delegations(goal_id);
            CREATE INDEX IF NOT EXISTS idx_delegations_task ON delegations(task_run_id);
            CREATE TABLE IF NOT EXISTS delegation_grants(grant_id TEXT PRIMARY KEY,delegation_request_id TEXT NOT NULL UNIQUE,goal_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_delegation_grants_goal ON delegation_grants(goal_id);
            CREATE TABLE IF NOT EXISTS semantic_documents(document_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS safety_advisories(advisory_id TEXT PRIMARY KEY,reference TEXT,payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_safety_advisories_reference ON safety_advisories(reference);
            CREATE TABLE IF NOT EXISTS document_records(document_id TEXT PRIMARY KEY,owner_user_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_document_records_owner ON document_records(owner_user_id);
            CREATE TABLE IF NOT EXISTS experiments(experiment_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS learning_plans(plan_id TEXT PRIMARY KEY,owner_user_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_learning_plans_owner ON learning_plans(owner_user_id);
            CREATE TABLE IF NOT EXISTS device_identities(device_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS device_tokens(token_hash TEXT PRIMARY KEY,device_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS enrollment_codes(code_hash TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS conversation_messages(message_id TEXT PRIMARY KEY,session_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS connector_states(connector_id TEXT NOT NULL,owner_user_id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(connector_id,owner_user_id));
            CREATE INDEX IF NOT EXISTS idx_connector_states_owner ON connector_states(owner_user_id,connector_id);
            CREATE TABLE IF NOT EXISTS connector_invocations(request_id TEXT PRIMARY KEY,connector_id TEXT NOT NULL,owner_user_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_connector_invocations_owner ON connector_invocations(owner_user_id,connector_id);
            CREATE TABLE IF NOT EXISTS image_generation_requests(request_id TEXT PRIMARY KEY,owner_user_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_image_generation_owner ON image_generation_requests(owner_user_id);
            CREATE TABLE IF NOT EXISTS voice_sessions(session_id TEXT PRIMARY KEY,owner_user_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_voice_sessions_owner ON voice_sessions(owner_user_id);
            CREATE TABLE IF NOT EXISTS voice_events(id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL,event_type TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_voice_events_session ON voice_events(session_id,id);
            CREATE TABLE IF NOT EXISTS personal_settings(setting_key TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS operation_traces(id INTEGER PRIMARY KEY AUTOINCREMENT,trace_id TEXT NOT NULL,goal_id TEXT,task_run_id TEXT,payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_operation_traces_trace ON operation_traces(trace_id,id);
            CREATE INDEX IF NOT EXISTS idx_operation_traces_goal ON operation_traces(goal_id,id);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,goal_id TEXT NOT NULL,event_type TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_events_goal ON events(goal_id,id);
            ''')
    @staticmethod
    def _dump(v): return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    def _save(self,table,key_col,key,goal_id,payload):
        with self.connect() as db: db.execute(f'INSERT INTO {table}({key_col},goal_id,payload) VALUES(?,?,?) ON CONFLICT({key_col}) DO UPDATE SET payload=excluded.payload',(key,goal_id,self._dump(payload)))
    def _load_payload(self,table,key_col,key):
        with self.connect() as db:r=db.execute(f'SELECT payload FROM {table} WHERE {key_col}=?',(key,)).fetchone()
        if r is None:raise KeyError(key)
        return json.loads(r[0])
    def save_goal(self,g):
        with self.connect() as db:db.execute('INSERT INTO goals VALUES(?,?) ON CONFLICT(goal_id) DO UPDATE SET payload=excluded.payload',(g.goal_id,self._dump(g.to_dict())))
    def load_goal(self,gid):
        with self.connect() as db:r=db.execute('SELECT payload FROM goals WHERE goal_id=?',(gid,)).fetchone()
        if r is None:raise KeyError(gid)
        d=json.loads(r[0]);d['status']=GoalStatus(d['status']);return Goal(**d)
    def save_plan(self,p): self._save('plans','plan_id',p.plan_id,p.goal_id,p.to_dict())
    def load_plan(self,pid):
        d=self._load_payload('plans','plan_id',pid);steps=[]
        for s in d['steps']:s['status']=StepStatus(s['status']);steps.append(PlanStep(**s))
        return Plan(d['plan_id'],d['goal_id'],steps,d['created_at'],d.get('proposal_id'))
    def save_plan_proposal(self,p): self._save('plan_proposals','proposal_id',p.proposal_id,p.goal_id,p.to_dict())
    def save_task_run(self,r): self._save('task_runs','task_run_id',r.task_run_id,r.goal_id,r.to_dict())
    def load_task_run_for_goal(self,gid):
        with self.connect() as db:r=db.execute('SELECT payload FROM task_runs WHERE goal_id=? ORDER BY rowid DESC LIMIT 1',(gid,)).fetchone()
        if r is None:raise KeyError(gid)
        return TaskRun(**json.loads(r[0]))
    def save_permission(self,gid,p): self._save('permissions','permission_id',p.permission_id,gid,p.to_dict())
    def permissions_for_goal(self,gid):
        with self.connect() as db:rows=db.execute('SELECT payload FROM permissions WHERE goal_id=? ORDER BY rowid',(gid,)).fetchall()
        out=[]
        for r in rows:
            d=json.loads(r[0]);d['effect']=PermissionEffect(d['effect']);d['status']=PermissionStatus(d['status']);out.append(Permission(**d))
        return out
    def save_risk(self,gid,r): self._save('risks','risk_id',r.risk_id,gid,r.to_dict())
    def risks_for_goal(self,gid):
        with self.connect() as db:rows=db.execute('SELECT payload FROM risks WHERE goal_id=? ORDER BY rowid',(gid,)).fetchall()
        out=[]
        for r in rows:
            d=json.loads(r[0]);d['level']=RiskLevel(d['level']);out.append(RiskEvaluation(**d))
        return out
    def save_approval(self,a): self._save('approvals','approval_id',a.approval_id,a.goal_id,a.to_dict())
    def load_approval(self,aid):
        d=self._load_payload('approvals','approval_id',aid);d['risk']=RiskLevel(d['risk']);d['status']=ApprovalStatus(d['status']);return Approval(**d)
    def approvals_for_goal(self,gid):
        with self.connect() as db:rows=db.execute('SELECT payload FROM approvals WHERE goal_id=? ORDER BY rowid',(gid,)).fetchall()
        out=[]
        for r in rows:
            d=json.loads(r[0]);d['risk']=RiskLevel(d['risk']);d['status']=ApprovalStatus(d['status']);out.append(Approval(**d))
        return out
    def save_criterion(self,c): self._save('criteria','criterion_id',c.criterion_id,c.goal_id,c.to_dict())
    def criteria_for_goal(self,gid):
        with self.connect() as db:rows=db.execute('SELECT payload FROM criteria WHERE goal_id=? ORDER BY rowid',(gid,)).fetchall()
        out=[]
        for r in rows:
            d=json.loads(r[0]);d['status']=CriterionStatus(d['status']);out.append(GoalSuccessCriterion(**d))
        return out
    def save_provenance(self,gid,p): self._save('model_provenance','request_id',p.request_id,gid,p.to_dict())
    def provenance_for_goal(self,gid):
        with self.connect() as db:rows=db.execute('SELECT payload FROM model_provenance WHERE goal_id=? ORDER BY rowid',(gid,)).fetchall()
        return [json.loads(r[0]) for r in rows]
    def save_operation_trace(self,trace):
        payload=trace.to_dict() if hasattr(trace,'to_dict') else dict(trace)
        with self.connect() as db:db.execute('INSERT INTO operation_traces(trace_id,goal_id,task_run_id,payload) VALUES(?,?,?,?)',(payload['trace_id'],payload.get('goal_id'),payload.get('task_run_id'),self._dump(payload)))
    def operation_traces(self,*,goal_id=None,trace_id=None):
        clauses=[];params=[]
        if goal_id is not None:clauses.append('goal_id=?');params.append(goal_id)
        if trace_id is not None:clauses.append('trace_id=?');params.append(trace_id)
        where=(' WHERE '+' AND '.join(clauses)) if clauses else ''
        with self.connect() as db:rows=db.execute('SELECT payload FROM operation_traces'+where+' ORDER BY id',params).fetchall()
        return [json.loads(r[0]) for r in rows]
    def event(self,gid,event_type,payload,created_at):
        with self.connect() as db:db.execute('INSERT INTO events(goal_id,event_type,payload,created_at) VALUES(?,?,?,?)',(gid,event_type,self._dump(payload),created_at))
    def events(self,gid):
        with self.connect() as db:rows=db.execute('SELECT event_type,payload,created_at FROM events WHERE goal_id=? ORDER BY id',(gid,)).fetchall()
        return [{'event_type':r[0],'payload':json.loads(r[1]),'created_at':r[2]} for r in rows]
    def save_session(self,s):
        with self.connect() as db:db.execute('INSERT INTO sessions VALUES(?,?) ON CONFLICT(session_id) DO UPDATE SET payload=excluded.payload',(s.session_id,self._dump(s.to_dict())))
    def load_session(self,sid):
        from .sessions import Session
        with self.connect() as db:r=db.execute('SELECT payload FROM sessions WHERE session_id=?',(sid,)).fetchone()
        if r is None:raise KeyError(sid)
        return Session(**json.loads(r[0]))
    def save_background_task(self,t): self._save('background_tasks','background_id',t.background_id,t.goal_id,t.to_dict())
    def load_background_task(self,bid):
        from .background import BackgroundTask
        d=self._load_payload('background_tasks','background_id',bid);return BackgroundTask(**d)
    def background_tasks(self):
        from .background import BackgroundTask
        with self.connect() as db:rows=db.execute('SELECT payload FROM background_tasks ORDER BY rowid').fetchall()
        return [BackgroundTask(**json.loads(r[0])) for r in rows]
    def save_automation_binding(self,b):
        with self.connect() as db:db.execute('INSERT INTO automation_bindings VALUES(?,?) ON CONFLICT(automation_id) DO UPDATE SET payload=excluded.payload',(int(b.automation_id),self._dump(b.to_dict())))
    def load_automation_binding(self,automation_id):
        from .automation_orchestration import AutomationBinding
        with self.connect() as db:r=db.execute('SELECT payload FROM automation_bindings WHERE automation_id=?',(int(automation_id),)).fetchone()
        if r is None:raise KeyError(automation_id)
        return AutomationBinding(**json.loads(r[0]))
    def automation_bindings(self):
        from .automation_orchestration import AutomationBinding
        with self.connect() as db:rows=db.execute('SELECT payload FROM automation_bindings ORDER BY automation_id').fetchall()
        return [AutomationBinding(**json.loads(r[0])) for r in rows]

    def save_rollback_record(self,record):
        payload=record.to_dict() if hasattr(record,'to_dict') else dict(record)
        with self.connect() as db:db.execute('INSERT INTO rollback_records(rollback_id,payload) VALUES(?,?) ON CONFLICT(rollback_id) DO UPDATE SET payload=excluded.payload',(payload['rollback_id'],self._dump(payload)))
    def load_rollback_record(self,rollback_id):
        from .rollback import RollbackRecord
        with self.connect() as db:r=db.execute('SELECT payload FROM rollback_records WHERE rollback_id=?',(rollback_id,)).fetchone()
        if r is None:raise KeyError(rollback_id)
        return RollbackRecord(**json.loads(r[0]))
    def rollback_records(self):
        from .rollback import RollbackRecord
        with self.connect() as db:rows=db.execute('SELECT payload FROM rollback_records ORDER BY rowid').fetchall()
        return [RollbackRecord(**json.loads(r[0])) for r in rows]

    def save_learning_plan(self,plan):
        payload=plan.to_dict() if hasattr(plan,'to_dict') else dict(plan)
        with self.connect() as db:db.execute('INSERT INTO learning_plans(plan_id,owner_user_id,payload) VALUES(?,?,?) ON CONFLICT(plan_id) DO UPDATE SET owner_user_id=excluded.owner_user_id,payload=excluded.payload',(payload['plan_id'],payload['owner_user_id'],self._dump(payload)))
    def load_learning_plan(self,plan_id):
        from .learning_orchestration import LearningPlanState
        with self.connect() as db:r=db.execute('SELECT payload FROM learning_plans WHERE plan_id=?',(str(plan_id),)).fetchone()
        if r is None:raise KeyError(plan_id)
        return LearningPlanState(**json.loads(r[0]))
    def learning_plans(self,*,owner_user_id,limit=20):
        from .learning_orchestration import LearningPlanState
        lim=max(1,min(int(limit),100))
        with self.connect() as db:rows=db.execute('SELECT payload FROM learning_plans WHERE owner_user_id=? ORDER BY rowid DESC LIMIT ?',(owner_user_id,lim)).fetchall()
        return [LearningPlanState(**json.loads(r[0])) for r in rows]

    def save_proactive_event(self,e):
        with self.connect() as db:db.execute('INSERT INTO proactive_events VALUES(?,?) ON CONFLICT(event_id) DO UPDATE SET payload=excluded.payload',(e.event_id,self._dump(e.to_dict())))
    def load_proactive_event(self,eid):
        from .proactive import ProactiveEvent
        with self.connect() as db:r=db.execute('SELECT payload FROM proactive_events WHERE event_id=?',(eid,)).fetchone()
        if r is None:raise KeyError(eid)
        return ProactiveEvent(**json.loads(r[0]))
    def proactive_events(self,limit=1000):
        from .proactive import ProactiveEvent
        with self.connect() as db:rows=db.execute('SELECT payload FROM proactive_events ORDER BY rowid DESC LIMIT ?',(max(1,min(int(limit),1000)),)).fetchall()
        return [ProactiveEvent(**json.loads(r[0])) for r in rows]
    def clear_criteria(self,gid):
        with self.connect() as db:db.execute('DELETE FROM criteria WHERE goal_id=?',(gid,))
    def recent_goals(self,limit=10):
        with self.connect() as db:rows=db.execute('SELECT payload FROM goals ORDER BY rowid DESC LIMIT ?',(max(1,min(int(limit),100)),)).fetchall()
        return [json.loads(r[0]) for r in rows]
    def recent_events(self,limit=20):
        with self.connect() as db:rows=db.execute('SELECT id,goal_id,event_type,payload,created_at FROM events ORDER BY id DESC LIMIT ?',(max(1,min(int(limit),200)),)).fetchall()
        return [{'event_id':r[0],'goal_id':r[1],'event_type':r[2],'payload':json.loads(r[3]),'created_at':r[4]} for r in rows]
    def cancel_pending_approvals(self,gid,decision_at):
        for approval in self.approvals_for_goal(gid):
            if approval.status==ApprovalStatus.PENDING:
                approval.status=ApprovalStatus.CANCELLED;approval.decision_at=decision_at;approval.approved_by='system_cancel';self.save_approval(approval)

    def save_perception_observation(self,observation):
        payload=observation.to_dict() if hasattr(observation,'to_dict') else dict(observation)
        with self.connect() as db:db.execute('INSERT INTO perception_observations(observation_id,robot_id,payload) VALUES(?,?,?) ON CONFLICT(observation_id) DO UPDATE SET payload=excluded.payload',(payload['observation_id'],payload['robot_id'],self._dump(payload)))
    def load_perception_observation(self,observation_id):
        from .perception import PerceptionObservation
        with self.connect() as db:r=db.execute('SELECT payload FROM perception_observations WHERE observation_id=?',(observation_id,)).fetchone()
        if r is None:raise KeyError(observation_id)
        return PerceptionObservation(**json.loads(r[0]))
    def perception_observations(self,*,robot_id=None):
        query='SELECT payload FROM perception_observations';params=[]
        if robot_id is not None:query+=' WHERE robot_id=?';params.append(robot_id)
        query+=' ORDER BY rowid'
        with self.connect() as db:rows=db.execute(query,params).fetchall()
        return [json.loads(r[0]) for r in rows]

    def save_world_node(self,node):
        with self.connect() as db:db.execute('INSERT INTO world_nodes VALUES(?,?) ON CONFLICT(node_id) DO UPDATE SET payload=excluded.payload',(node.node_id,self._dump(node.to_dict())))
    def world_nodes(self):
        with self.connect() as db:rows=db.execute('SELECT payload FROM world_nodes ORDER BY rowid').fetchall()
        return [json.loads(r[0]) for r in rows]
    def save_world_edge(self,edge):
        with self.connect() as db:db.execute('INSERT INTO world_edges VALUES(?,?) ON CONFLICT(edge_id) DO UPDATE SET payload=excluded.payload',(edge.edge_id,self._dump(edge.to_dict())))
    def world_edges(self):
        with self.connect() as db:rows=db.execute('SELECT payload FROM world_edges ORDER BY rowid').fetchall()
        return [json.loads(r[0]) for r in rows]

    def save_daily_brief(self,b):
        payload=b.to_dict() if hasattr(b,'to_dict') else dict(b)
        with self.connect() as db:db.execute('INSERT INTO daily_briefs(brief_id,owner_user_id,day,payload) VALUES(?,?,?,?) ON CONFLICT(brief_id) DO UPDATE SET payload=excluded.payload',(payload['brief_id'],payload['owner_user_id'],payload['day'],self._dump(payload)))
    def load_daily_brief(self,brief_id):
        from .daily_os import DailyBrief
        with self.connect() as db:r=db.execute('SELECT payload FROM daily_briefs WHERE brief_id=?',(brief_id,)).fetchone()
        if r is None:raise KeyError(brief_id)
        return DailyBrief(**json.loads(r[0]))
    def daily_briefs(self,*,owner_user_id=None):
        from .daily_os import DailyBrief
        q='SELECT payload FROM daily_briefs';params=[]
        if owner_user_id is not None:q+=' WHERE owner_user_id=?';params.append(owner_user_id)
        q+=' ORDER BY day,rowid'
        with self.connect() as db:rows=db.execute(q,params).fetchall()
        return [DailyBrief(**json.loads(r[0])) for r in rows]
    def latest_daily_brief(self,owner_user_id,*,day=None,before_day=None):
        from .daily_os import DailyBrief
        q='SELECT payload FROM daily_briefs WHERE owner_user_id=?';params=[owner_user_id]
        if day is not None:q+=' AND day=?';params.append(day)
        if before_day is not None:q+=' AND day<?';params.append(before_day)
        q+=' ORDER BY day DESC,rowid DESC LIMIT 1'
        with self.connect() as db:r=db.execute(q,params).fetchone()
        return None if r is None else DailyBrief(**json.loads(r[0]))

    def save_notification(self,n):
        with self.connect() as db:db.execute('INSERT INTO notifications VALUES(?,?) ON CONFLICT(notification_id) DO UPDATE SET payload=excluded.payload',(n.notification_id,self._dump(n.to_dict())))
    def notifications(self):
        with self.connect() as db:rows=db.execute('SELECT payload FROM notifications ORDER BY rowid').fetchall()
        return [json.loads(r[0]) for r in rows]
    def save_notification_channel_state(self,state):
        payload=state.to_dict() if hasattr(state,'to_dict') else dict(state)
        with self.connect() as db:db.execute('INSERT INTO notification_channel_states(channel_state_id,owner_user_id,channel,device_id,payload) VALUES(?,?,?,?,?) ON CONFLICT(channel_state_id) DO UPDATE SET owner_user_id=excluded.owner_user_id,channel=excluded.channel,device_id=excluded.device_id,payload=excluded.payload',(payload['channel_state_id'],payload['owner_user_id'],payload['channel'],payload.get('device_id'),self._dump(payload)))
    def notification_channel_states(self,*,owner_user_id=None,channel=None):
        q='SELECT payload FROM notification_channel_states';clauses=[];params=[]
        if owner_user_id is not None:clauses.append('owner_user_id=?');params.append(owner_user_id)
        if channel is not None:clauses.append('channel=?');params.append(channel)
        if clauses:q+=' WHERE '+' AND '.join(clauses)
        q+=' ORDER BY rowid'
        with self.connect() as db:rows=db.execute(q,params).fetchall()
        return [json.loads(r[0]) for r in rows]
    def save_notification_delivery_attempt(self,attempt):
        payload=attempt.to_dict() if hasattr(attempt,'to_dict') else dict(attempt)
        with self.connect() as db:db.execute('INSERT INTO notification_delivery_attempts(attempt_id,decision_id,notification_id,owner_user_id,channel,payload) VALUES(?,?,?,?,?,?) ON CONFLICT(attempt_id) DO UPDATE SET payload=excluded.payload',(payload['attempt_id'],payload['decision_id'],payload['notification_id'],payload['owner_user_id'],payload['channel'],self._dump(payload)))
    def notification_delivery_attempt(self,attempt_id):
        with self.connect() as db:r=db.execute('SELECT payload FROM notification_delivery_attempts WHERE attempt_id=?',(attempt_id,)).fetchone()
        return None if r is None else json.loads(r[0])
    def notification_delivery_attempts(self,*,owner_user_id=None,notification_id=None,decision_id=None,channel=None):
        q='SELECT payload FROM notification_delivery_attempts';clauses=[];params=[]
        for key,value in (('owner_user_id',owner_user_id),('notification_id',notification_id),('decision_id',decision_id),('channel',channel)):
            if value is not None:clauses.append(key+'=?');params.append(value)
        if clauses:q+=' WHERE '+' AND '.join(clauses)
        q+=' ORDER BY rowid'
        with self.connect() as db:rows=db.execute(q,params).fetchall()
        return [json.loads(r[0]) for r in rows]

    def save_notification_decision(self,d):
        payload=d.to_dict() if hasattr(d,'to_dict') else dict(d)
        with self.connect() as db:db.execute('INSERT INTO notification_decisions(decision_id,candidate_id,owner_user_id,payload) VALUES(?,?,?,?) ON CONFLICT(decision_id) DO UPDATE SET payload=excluded.payload',(payload['decision_id'],payload['candidate_id'],payload['owner_user_id'],self._dump(payload)))
    def notification_decision_for_candidate(self,candidate_id):
        with self.connect() as db:r=db.execute('SELECT payload FROM notification_decisions WHERE candidate_id=?',(candidate_id,)).fetchone()
        return None if r is None else json.loads(r[0])
    def notification_decisions(self,*,owner_user_id=None):
        q='SELECT payload FROM notification_decisions';params=[]
        if owner_user_id is not None:q+=' WHERE owner_user_id=?';params.append(owner_user_id)
        q+=' ORDER BY rowid'
        with self.connect() as db:rows=db.execute(q,params).fetchall()
        return [json.loads(r[0]) for r in rows]

    def save_improvement_candidate(self,c):
        with self.connect() as db:db.execute('INSERT INTO improvement_candidates VALUES(?,?) ON CONFLICT(candidate_id) DO UPDATE SET payload=excluded.payload',(c.candidate_id,self._dump(c.to_dict())))
    def improvement_candidates(self):
        with self.connect() as db:rows=db.execute('SELECT payload FROM improvement_candidates ORDER BY rowid').fetchall()
        return [json.loads(r[0]) for r in rows]
    def save_memory_candidate(self,c):
        payload=c.to_dict() if hasattr(c,'to_dict') else dict(c)
        with self.connect() as db:db.execute('INSERT INTO memory_candidates(candidate_id,goal_id,memory_id,payload) VALUES(?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET memory_id=excluded.memory_id,payload=excluded.payload',(payload['candidate_id'],payload['goal_id'],payload.get('memory_id'),self._dump(payload)))
    def load_memory_candidate(self,candidate_id):
        with self.connect() as db:r=db.execute('SELECT payload FROM memory_candidates WHERE candidate_id=?',(candidate_id,)).fetchone()
        if r is None:raise KeyError(candidate_id)
        return json.loads(r[0])
    def memory_candidates(self,*,goal_id=None,memory_id=None):
        clauses=[];params=[]
        if goal_id is not None:clauses.append('goal_id=?');params.append(goal_id)
        if memory_id is not None:clauses.append('memory_id=?');params.append(memory_id)
        where=(' WHERE '+' AND '.join(clauses)) if clauses else ''
        with self.connect() as db:rows=db.execute('SELECT payload FROM memory_candidates'+where+' ORDER BY rowid',params).fetchall()
        return [json.loads(r[0]) for r in rows]

    def save_delegation(self,record):
        payload=record.to_dict() if hasattr(record,'to_dict') else dict(record);request=payload['request']
        with self.connect() as db:db.execute('INSERT INTO delegations(request_id,goal_id,task_run_id,payload) VALUES(?,?,?,?) ON CONFLICT(request_id) DO UPDATE SET payload=excluded.payload',(request['request_id'],request['goal_id'],request['task_run_id'],self._dump(payload)))
    def load_delegation(self,request_id):
        with self.connect() as db:r=db.execute('SELECT payload FROM delegations WHERE request_id=?',(request_id,)).fetchone()
        if r is None:raise KeyError(request_id)
        return json.loads(r[0])
    def delegations(self,*,goal_id=None,task_run_id=None):
        clauses=[];params=[]
        if goal_id is not None:clauses.append('goal_id=?');params.append(goal_id)
        if task_run_id is not None:clauses.append('task_run_id=?');params.append(task_run_id)
        where=(' WHERE '+' AND '.join(clauses)) if clauses else ''
        with self.connect() as db:rows=db.execute('SELECT payload FROM delegations'+where+' ORDER BY rowid',params).fetchall()
        return [json.loads(r[0]) for r in rows]

    def save_delegation_grant(self,grant):
        payload=grant.to_dict() if hasattr(grant,'to_dict') else dict(grant)
        with self.connect() as db:db.execute('INSERT INTO delegation_grants(grant_id,delegation_request_id,goal_id,payload) VALUES(?,?,?,?) ON CONFLICT(grant_id) DO UPDATE SET payload=excluded.payload',(payload['grant_id'],payload['delegation_request_id'],payload['goal_id'],self._dump(payload)))
    def load_delegation_grant(self,grant_id):
        with self.connect() as db:r=db.execute('SELECT payload FROM delegation_grants WHERE grant_id=?',(grant_id,)).fetchone()
        if r is None:raise KeyError(grant_id)
        return json.loads(r[0])
    def delegation_grant_for_request(self,request_id):
        with self.connect() as db:r=db.execute('SELECT payload FROM delegation_grants WHERE delegation_request_id=?',(request_id,)).fetchone()
        if r is None:raise KeyError(request_id)
        return json.loads(r[0])
    def update_delegation_grant_payload(self,grant_id,payload):
        with self.connect() as db:
            cur=db.execute('UPDATE delegation_grants SET payload=? WHERE grant_id=?',(self._dump(payload),grant_id))
            if cur.rowcount!=1:raise KeyError(grant_id)

    def save_document_record(self,r):
        payload=r.to_dict() if hasattr(r,'to_dict') else dict(r)
        with self.connect() as db:db.execute('INSERT INTO document_records(document_id,owner_user_id,payload) VALUES(?,?,?) ON CONFLICT(document_id) DO UPDATE SET owner_user_id=excluded.owner_user_id,payload=excluded.payload',(payload['document_id'],payload['owner_user_id'],self._dump(payload)))
    def load_document_record(self,document_id):
        from .document_intelligence import DocumentRecord
        with self.connect() as db:r=db.execute('SELECT payload FROM document_records WHERE document_id=?',(document_id,)).fetchone()
        if r is None:raise KeyError(document_id)
        return DocumentRecord(**json.loads(r[0]))
    def document_records(self):
        from .document_intelligence import DocumentRecord
        with self.connect() as db:rows=db.execute('SELECT payload FROM document_records ORDER BY rowid').fetchall()
        return [DocumentRecord(**json.loads(r[0])) for r in rows]

    def save_safety_advisory(self,payload):
        value=dict(payload)
        with self.connect() as db:db.execute('INSERT INTO safety_advisories(advisory_id,reference,payload) VALUES(?,?,?) ON CONFLICT(advisory_id) DO UPDATE SET reference=excluded.reference,payload=excluded.payload',(value['advisory_id'],value.get('reference'),self._dump(value)))
    def safety_advisories(self,*,reference=None):
        q='SELECT payload FROM safety_advisories';params=[]
        if reference is not None:q+=' WHERE reference=?';params.append(reference)
        q+=' ORDER BY rowid'
        with self.connect() as db:rows=db.execute(q,params).fetchall()
        return [json.loads(r[0]) for r in rows]

    def save_semantic_document(self,document_id,payload):
        with self.connect() as db:db.execute('INSERT INTO semantic_documents VALUES(?,?) ON CONFLICT(document_id) DO UPDATE SET payload=excluded.payload',(document_id,self._dump(payload)))
    def semantic_documents(self):
        with self.connect() as db:rows=db.execute('SELECT payload FROM semantic_documents ORDER BY rowid').fetchall()
        return [json.loads(r[0]) for r in rows]

    def save_experiment(self,e):
        with self.connect() as db:db.execute('INSERT INTO experiments VALUES(?,?) ON CONFLICT(experiment_id) DO UPDATE SET payload=excluded.payload',(e.experiment_id,self._dump(e.to_dict())))
    def experiments(self):
        with self.connect() as db:rows=db.execute('SELECT payload FROM experiments ORDER BY rowid').fetchall()
        return [json.loads(r[0]) for r in rows]
    def save_device_identity(self,device_id,payload):
        with self.connect() as db:db.execute('INSERT INTO device_identities VALUES(?,?) ON CONFLICT(device_id) DO UPDATE SET payload=excluded.payload',(device_id,self._dump(payload)))
    def device_identities(self):
        with self.connect() as db:rows=db.execute('SELECT payload FROM device_identities ORDER BY rowid').fetchall()
        return [json.loads(r[0]) for r in rows]
    def save_device_token(self,token_hash,device_id,payload):
        with self.connect() as db:db.execute('INSERT INTO device_tokens VALUES(?,?,?) ON CONFLICT(token_hash) DO UPDATE SET device_id=excluded.device_id,payload=excluded.payload',(token_hash,device_id,self._dump(payload)))
    def load_device_token(self,token_hash):
        with self.connect() as db:r=db.execute('SELECT device_id,payload FROM device_tokens WHERE token_hash=?',(token_hash,)).fetchone()
        if r is None:raise KeyError(token_hash)
        return r[0],json.loads(r[1])
    def delete_device_tokens(self,device_id):
        with self.connect() as db:db.execute('DELETE FROM device_tokens WHERE device_id=?',(device_id,))
    def save_enrollment_code(self,code_hash,payload):
        with self.connect() as db:db.execute('INSERT INTO enrollment_codes VALUES(?,?) ON CONFLICT(code_hash) DO UPDATE SET payload=excluded.payload',(code_hash,self._dump(payload)))
    def load_enrollment_code(self,code_hash):
        with self.connect() as db:r=db.execute('SELECT payload FROM enrollment_codes WHERE code_hash=?',(code_hash,)).fetchone()
        if r is None:raise KeyError(code_hash)
        return json.loads(r[0])
    def delete_enrollment_code(self,code_hash):
        with self.connect() as db:db.execute('DELETE FROM enrollment_codes WHERE code_hash=?',(code_hash,))
    def save_connector_state(self,state):
        payload=state.to_dict() if hasattr(state,'to_dict') else dict(state)
        with self.connect() as db:db.execute('INSERT INTO connector_states(connector_id,owner_user_id,payload) VALUES(?,?,?) ON CONFLICT(connector_id,owner_user_id) DO UPDATE SET payload=excluded.payload',(payload['connector_id'],payload['owner_user_id'],self._dump(payload)))
    def connector_state(self,connector_id,*,owner_user_id='user'):
        with self.connect() as db:r=db.execute('SELECT payload FROM connector_states WHERE connector_id=? AND owner_user_id=?',(connector_id,owner_user_id)).fetchone()
        return None if r is None else json.loads(r[0])
    def connector_states(self,*,owner_user_id=None):
        q='SELECT payload FROM connector_states';params=[]
        if owner_user_id is not None:q+=' WHERE owner_user_id=?';params.append(owner_user_id)
        q+=' ORDER BY owner_user_id,connector_id'
        with self.connect() as db:rows=db.execute(q,params).fetchall()
        return [json.loads(r[0]) for r in rows]
    def save_connector_invocation(self,payload):
        value=dict(payload)
        with self.connect() as db:db.execute('INSERT INTO connector_invocations(request_id,connector_id,owner_user_id,payload) VALUES(?,?,?,?) ON CONFLICT(request_id) DO UPDATE SET connector_id=excluded.connector_id,owner_user_id=excluded.owner_user_id,payload=excluded.payload',(value['request_id'],value['connector_id'],value['owner_user_id'],self._dump(value)))
    def connector_invocations(self,*,owner_user_id=None,connector_id=None):
        clauses=[];params=[]
        if owner_user_id is not None:clauses.append('owner_user_id=?');params.append(owner_user_id)
        if connector_id is not None:clauses.append('connector_id=?');params.append(connector_id)
        q='SELECT payload FROM connector_invocations'+((' WHERE '+' AND '.join(clauses)) if clauses else '')+' ORDER BY rowid'
        with self.connect() as db:rows=db.execute(q,params).fetchall()
        return [json.loads(r[0]) for r in rows]

    def save_image_generation_request(self,payload):
        value=dict(payload)
        with self.connect() as db:db.execute('INSERT INTO image_generation_requests(request_id,owner_user_id,payload) VALUES(?,?,?) ON CONFLICT(request_id) DO UPDATE SET owner_user_id=excluded.owner_user_id,payload=excluded.payload',(value['request_id'],value['owner_user_id'],self._dump(value)))
    def image_generation_request(self,request_id):
        with self.connect() as db:r=db.execute('SELECT payload FROM image_generation_requests WHERE request_id=?',(request_id,)).fetchone()
        return None if r is None else json.loads(r[0])
    def image_generation_requests(self,*,owner_user_id=None):
        q='SELECT payload FROM image_generation_requests';params=[]
        if owner_user_id is not None:q+=' WHERE owner_user_id=?';params.append(owner_user_id)
        q+=' ORDER BY rowid'
        with self.connect() as db:rows=db.execute(q,params).fetchall()
        return [json.loads(r[0]) for r in rows]

    def save_voice_session(self,session):
        payload=session.to_dict() if hasattr(session,'to_dict') else dict(session)
        with self.connect() as db:db.execute('INSERT INTO voice_sessions(session_id,owner_user_id,payload) VALUES(?,?,?) ON CONFLICT(session_id) DO UPDATE SET owner_user_id=excluded.owner_user_id,payload=excluded.payload',(payload['session_id'],payload['owner_user_id'],self._dump(payload)))
    def load_voice_session(self,session_id):
        from .voice_runtime import VoiceSession
        with self.connect() as db:r=db.execute('SELECT payload FROM voice_sessions WHERE session_id=?',(session_id,)).fetchone()
        if r is None:raise KeyError(session_id)
        return VoiceSession(**json.loads(r[0]))
    def voice_sessions(self,*,owner_user_id=None):
        q='SELECT payload FROM voice_sessions';params=[]
        if owner_user_id is not None:q+=' WHERE owner_user_id=?';params.append(owner_user_id)
        q+=' ORDER BY rowid'
        with self.connect() as db:rows=db.execute(q,params).fetchall()
        return [json.loads(r[0]) for r in rows]
    def save_voice_event(self,session_id,event_type,payload,created_at):
        value=dict(payload or {})
        for forbidden in ('audio','raw_audio','payload','api_key','authorization','secret','token'):
            if forbidden in value:raise ValueError('raw/sensitive voice event field cannot be persisted:'+forbidden)
        with self.connect() as db:db.execute('INSERT INTO voice_events(session_id,event_type,payload,created_at) VALUES(?,?,?,?)',(session_id,event_type,self._dump(value),created_at))
    def voice_events(self,session_id):
        with self.connect() as db:rows=db.execute('SELECT id,event_type,payload,created_at FROM voice_events WHERE session_id=? ORDER BY id',(session_id,)).fetchall()
        return [{'event_id':r[0],'event_type':r[1],'payload':json.loads(r[2]),'created_at':r[3]} for r in rows]

    def save_conversation_message(self,message_id,session_id,payload):
        with self.connect() as db:db.execute('INSERT INTO conversation_messages VALUES(?,?,?) ON CONFLICT(message_id) DO UPDATE SET payload=excluded.payload',(message_id,session_id,self._dump(payload)))
    def conversation_messages(self,session_id,limit=100):
        with self.connect() as db:rows=db.execute('SELECT payload FROM conversation_messages WHERE session_id=? ORDER BY rowid DESC LIMIT ?',(session_id,max(1,min(int(limit),500)))).fetchall()
        return [json.loads(r[0]) for r in reversed(rows)]
    def all_approvals(self):
        with self.connect() as db:rows=db.execute('SELECT payload FROM approvals ORDER BY rowid DESC').fetchall()
        out=[]
        for r in rows:
            d=json.loads(r[0]);d['risk']=RiskLevel(d['risk']);d['status']=ApprovalStatus(d['status']);out.append(Approval(**d))
        return out
    def all_task_runs(self,limit=100):
        with self.connect() as db:rows=db.execute('SELECT payload FROM task_runs ORDER BY rowid DESC LIMIT ?',(max(1,min(int(limit),500)),)).fetchall()
        return [json.loads(r[0]) for r in rows]
    def all_sessions(self,limit=100):
        with self.connect() as db:rows=db.execute('SELECT payload FROM sessions ORDER BY rowid DESC LIMIT ?',(max(1,min(int(limit),500)),)).fetchall()
        return [json.loads(r[0]) for r in rows]
    def save_setting(self,key,payload):
        with self.connect() as db:db.execute('INSERT INTO personal_settings VALUES(?,?) ON CONFLICT(setting_key) DO UPDATE SET payload=excluded.payload',(key,self._dump(payload)))
    def load_setting(self,key,default=None):
        with self.connect() as db:r=db.execute('SELECT payload FROM personal_settings WHERE setting_key=?',(key,)).fetchone()
        return default if r is None else json.loads(r[0])
