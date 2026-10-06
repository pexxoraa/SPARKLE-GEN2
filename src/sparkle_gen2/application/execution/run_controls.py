"""Durable cooperative controls and exclusive execution of each goal."""
from __future__ import annotations

import threading
import uuid

from ...core_time import now
from ...domain.models import GoalStatus


class RunControlService:
    def __init__(self, store):
        self.store = store
        self._local = threading.local()

    def state(self, goal_id):
        return self.store.load_setting('execution_control:' + goal_id, {}) or {}

    def request(self, goal_id, state, *, reason='user'):
        if state not in {'PAUSED', 'CANCELLED', 'RUNNING'}:
            raise ValueError('invalid execution control')
        self.store.save_setting('execution_control:' + goal_id, {
            'goal_id': goal_id, 'state': state, 'reason': reason, 'updated_at': now(),
        })

    def apply(self, goal, run):
        state = self.state(goal.goal_id).get('state')
        if state == 'CANCELLED':
            goal.status = GoalStatus.CANCELLED
            run.status = 'CANCELLED'
            run.current_step = None
        elif state == 'PAUSED':
            goal.status = GoalStatus.WAITING
            run.status = 'PAUSED'
            run.current_step = None
        return state in {'PAUSED', 'CANCELLED'}

    def execute(self, agent, goal_id, operation):
        active = getattr(self._local, 'active', set())
        if goal_id in active:
            return operation()
        lease_id = uuid.uuid4().hex
        if not self.store.claim_execution(goal_id, lease_id):
            return {'goal_id': goal_id, 'status': 'WAITING', 'text': 'This execution is already running. Inspect its saved progress.', 'checked': [], 'verified': [], 'approvals': []}
        self._local.active = active | {goal_id}
        try:
            return operation()
        finally:
            self._local.active = active
            self.store.release_execution(goal_id, lease_id)
