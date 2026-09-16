from __future__ import annotations

class ImageGenerationRuntime:
    def __init__(self,provider=None):self.provider=provider
    def health(self):return {'status':'CONNECTED' if self.provider else 'EXTERNALLY_BLOCKED'}
    def generate(self,prompt,*,approved=True):
        if self.provider is None:raise RuntimeError('external_dependency:image_generation_provider')
        if not approved:raise PermissionError('approval_required')
        result=self.provider(prompt)
        if not isinstance(result,dict) or 'artifact' not in result:raise RuntimeError('invalid_image_provider_result')
        return result
