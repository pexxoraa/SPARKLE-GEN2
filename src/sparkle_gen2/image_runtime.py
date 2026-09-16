from __future__ import annotations
from .core_time import now

class ImageGenerationRuntime:
    def __init__(self,provider=None):self.provider=provider
    def health(self):return {'status':'CONNECTED' if self.provider else 'EXTERNALLY_BLOCKED'}
    def generate(self,prompt,*,approved=True,goal_id=None,project_id=None,task_id=None):
        if self.provider is None:raise RuntimeError('external_dependency:image_generation_provider')
        if not approved:raise PermissionError('approval_required')
        result=self.provider(prompt)
        if not isinstance(result,dict) or 'artifact' not in result:raise RuntimeError('invalid_image_provider_result')
        out=dict(result);out['provenance']={'provider':getattr(self.provider,'name',type(self.provider).__name__),'generated_at':now(),'goal_id':goal_id,'project_id':project_id,'task_id':task_id}
        return out
