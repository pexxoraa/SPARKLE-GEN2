from __future__ import annotations
import json, sqlite3
from pathlib import Path
from typing import Any
from .models import Goal, GoalStatus, Plan, PlanStep, StepStatus, TaskRun

class Gen2Store:
    def __init__(self,path:str|Path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self._init()
    def connect(self):
        db=sqlite3.connect(self.path); db.row_factory=sqlite3.Row; return db
    def _init(self):
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS goals(goal_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS plans(plan_id TEXT PRIMARY KEY,goal_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS task_runs(task_run_id TEXT PRIMARY KEY,goal_id TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,goal_id TEXT NOT NULL,event_type TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_events_goal ON events(goal_id,id);
            """)
    @staticmethod
    def _dump(v:dict[str,Any])->str: return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    def save_goal(self,g:Goal):
        with self.connect() as db: db.execute("INSERT INTO goals VALUES(?,?) ON CONFLICT(goal_id) DO UPDATE SET payload=excluded.payload",(g.goal_id,self._dump(g.to_dict())))
    def load_goal(self,goal_id:str)->Goal:
        with self.connect() as db: row=db.execute("SELECT payload FROM goals WHERE goal_id=?",(goal_id,)).fetchone()
        if row is None: raise KeyError(goal_id)
        d=json.loads(row[0]); d['status']=GoalStatus(d['status']); return Goal(**d)
    def save_plan(self,p:Plan):
        with self.connect() as db: db.execute("INSERT INTO plans VALUES(?,?,?) ON CONFLICT(plan_id) DO UPDATE SET payload=excluded.payload",(p.plan_id,p.goal_id,self._dump(p.to_dict())))
    def load_plan(self,plan_id:str)->Plan:
        with self.connect() as db: row=db.execute("SELECT payload FROM plans WHERE plan_id=?",(plan_id,)).fetchone()
        if row is None: raise KeyError(plan_id)
        d=json.loads(row[0]); steps=[]
        for s in d['steps']:
            s['status']=StepStatus(s['status']); steps.append(PlanStep(**s))
        return Plan(d['plan_id'],d['goal_id'],steps,d['created_at'])
    def save_task_run(self,r:TaskRun):
        with self.connect() as db: db.execute("INSERT INTO task_runs VALUES(?,?,?) ON CONFLICT(task_run_id) DO UPDATE SET payload=excluded.payload",(r.task_run_id,r.goal_id,self._dump(r.to_dict())))
    def load_task_run_for_goal(self,goal_id:str)->TaskRun:
        with self.connect() as db: row=db.execute("SELECT payload FROM task_runs WHERE goal_id=? ORDER BY rowid DESC LIMIT 1",(goal_id,)).fetchone()
        if row is None: raise KeyError(goal_id)
        return TaskRun(**json.loads(row[0]))
    def event(self,goal_id:str,event_type:str,payload:dict[str,Any],created_at:str):
        with self.connect() as db: db.execute("INSERT INTO events(goal_id,event_type,payload,created_at) VALUES(?,?,?,?)",(goal_id,event_type,self._dump(payload),created_at))
    def events(self,goal_id:str)->list[dict[str,Any]]:
        with self.connect() as db: rows=db.execute("SELECT event_type,payload,created_at FROM events WHERE goal_id=? ORDER BY id",(goal_id,)).fetchall()
        return [{"event_type":r[0],"payload":json.loads(r[1]),"created_at":r[2]} for r in rows]
