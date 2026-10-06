"""Thin application facade for Personal OS records.

This is intentionally storage-agnostic: the current PersonalCore remains the
compatibility implementation while callers migrate to this stable use-case API.
"""
from __future__ import annotations
from typing import Any

class PersonalOSService:
    def __init__(self, core: Any): self._core=core
    def snapshot(self)->Any: return self._core.os_snapshot()
    def create_task(self, payload: dict[str,Any])->Any: return self._core.create_manual_task(payload)
    def create_goal(self, payload: dict[str,Any])->Any: return self._core.create_manual_goal(payload)
    def create_learning(self, payload: dict[str,Any])->Any: return self._core.create_manual_learning(payload)
    def save_record(self, kind: str, payload: dict[str,Any])->Any: return self._core.save_manual_record(kind,payload)
    def update_record(self, kind: str, record_id: str, payload: dict[str,Any])->Any: return self._core.update_manual_record(kind,record_id,payload)
    def delete_record(self, kind: str, record_id: str)->Any: return self._core.delete_manual_record(kind,record_id)
    def plan(self, kind: str, record_id: str)->Any: return self._core.plan_os_item(kind,record_id)
