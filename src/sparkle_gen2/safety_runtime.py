from __future__ import annotations

class SafetyModelRuntime:
    """Advisory model hook. Deterministic policy remains authoritative."""
    def __init__(self,classifier=None):self.classifier=classifier
    def health(self):return {'status':'CONNECTED' if self.classifier else 'EXTERNALLY_BLOCKED'}
    def classify(self,text):
        if self.classifier is None:raise RuntimeError('external_dependency:safety_model')
        result=self.classifier(text)
        if not isinstance(result,dict) or 'label' not in result:raise RuntimeError('invalid_safety_model_result')
        return result
