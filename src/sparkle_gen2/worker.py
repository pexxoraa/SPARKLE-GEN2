from __future__ import annotations
from .background import BackgroundTaskService

class BackgroundWorker:
    """One bounded worker pass. Scheduling/service supervision is deployment-owned."""
    def __init__(self,service:BackgroundTaskService): self.service=service
    def run_once(self,*,max_tasks=20):
        if not 1<=max_tasks<=100: raise ValueError('max_tasks out of range')
        processed=[]
        for task in self.service.store.background_tasks():
            if len(processed)>=max_tasks: break
            if task.state in {'QUEUED','RUNNING','WAITING','PAUSED'}:
                if task.state=='PAUSED': continue
                processed.append(self.service.resume(task.background_id).to_dict())
        return processed
