from __future__ import annotations
import json,sqlite3
from pathlib import Path
from typing import Any
from .models import *

class Gen2Store:
    def __init__(self,path:str|Path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self._init()
    def connect(self):
        db=sqlite3.connect(self.path); db.row_factory=sqlite3.Row; return db
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
    def save_risk(self,gid,r): self._save('risks','risk_id',r.risk_id,gid,r.to_dict())
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
    def save_proactive_event(self,e):
        with self.connect() as db:db.execute('INSERT INTO proactive_events VALUES(?,?) ON CONFLICT(event_id) DO UPDATE SET payload=excluded.payload',(e.event_id,self._dump(e.to_dict())))
    def load_proactive_event(self,eid):
        from .proactive import ProactiveEvent
        with self.connect() as db:r=db.execute('SELECT payload FROM proactive_events WHERE event_id=?',(eid,)).fetchone()
        if r is None:raise KeyError(eid)
        return ProactiveEvent(**json.loads(r[0]))
    def clear_criteria(self,gid):
        with self.connect() as db:db.execute('DELETE FROM criteria WHERE goal_id=?',(gid,))
    def cancel_pending_approvals(self,gid,decision_at):
        for approval in self.approvals_for_goal(gid):
            if approval.status==ApprovalStatus.PENDING:
                approval.status=ApprovalStatus.CANCELLED;approval.decision_at=decision_at;approval.approved_by='system_cancel';self.save_approval(approval)
