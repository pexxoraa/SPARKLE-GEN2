"""Thin application facade for Personal OS records.

This is intentionally storage-agnostic: the current PersonalCore remains the
compatibility implementation while callers migrate to this stable use-case API.
"""
from __future__ import annotations
from typing import Any

class PersonalOSService:
    def __init__(self, core: Any): self._core=core
    def snapshot(self,*,owner_user_id='user')->Any: return self._core.os_snapshot(owner_user_id=owner_user_id)
    def create_task(self,payload:dict[str,Any],*,owner_user_id='user')->Any:
        return self._core.create_manual_task(payload.get('title'),priority=payload.get('priority',5),deadline=payload.get('deadline'),metadata=payload.get('metadata'),owner_user_id=owner_user_id)
    def create_goal(self,payload:dict[str,Any],*,owner_user_id='user')->Any:
        return self._core.create_manual_goal(payload.get('title'),description=payload.get('description',''),priority=payload.get('priority',5),deadline=payload.get('deadline'),owner_user_id=owner_user_id)
    def create_learning(self,payload:dict[str,Any],*,owner_user_id='user')->Any:
        return self._core.create_manual_learning(payload.get('subject'),payload.get('objective'),payload.get('units',[]),owner_user_id=owner_user_id)
    def save_record(self,kind:str,payload:dict[str,Any],*,owner_user_id='user')->Any:
        return self._core.save_manual_record(kind,payload.get('title'),description=payload.get('description',''),status=payload.get('status','ACTIVE'),metadata=payload.get('metadata'),owner_user_id=owner_user_id)
    def update_record(self,kind:str,record_id:str,payload:dict[str,Any],*,owner_user_id='user')->Any:
        row=self._core.store.load_os_record(record_id)
        if row.get('owner_user_id')!=owner_user_id:raise PermissionError('os_record_owner_mismatch')
        if row.get('record_type')!=kind:raise ValueError('os_record_type_mismatch')
        return self._core.update_manual_record(record_id,payload,owner_user_id=owner_user_id)
    def delete_record(self,kind:str,record_id:str,*,owner_user_id='user')->Any:
        row=self._core.store.load_os_record(record_id)
        if row.get('owner_user_id')!=owner_user_id:raise PermissionError('os_record_owner_mismatch')
        if row.get('record_type')!=kind:raise ValueError('os_record_type_mismatch')
        return self._core.delete_manual_record(record_id,owner_user_id=owner_user_id)
    def plan(self,kind:str,record_id:str,*,owner_user_id='user')->Any: return self._core.plan_os_item(kind,record_id,owner_user_id=owner_user_id)
