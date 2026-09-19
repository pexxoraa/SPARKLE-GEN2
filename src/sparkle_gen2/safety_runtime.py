from __future__ import annotations
import uuid
from datetime import UTC,datetime

BLOCKED_EXTERNAL_CLASSIFICATIONS=frozenset({'SENSITIVE','HIGHLY_SENSITIVE','DEVICE_CONTROL'})

class SafetyModelRuntime:
    """Advisory model hook. Deterministic policy remains authoritative and may only be tightened by advice."""
    def __init__(self,classifier=None,*,model_manager=None,store=None,allow_external_sensitive=False):
        self.classifier=classifier;self.model_manager=model_manager;self.store=store;self.allow_external_sensitive=bool(allow_external_sensitive)
    def health(self):
        if self.classifier is not None:return {'status':'CONNECTED','source':'injected_classifier'}
        if self.model_manager is None:return {'status':'EXTERNALLY_BLOCKED'}
        status=self.model_manager.status('safety');return {'status':status['status'],'route':status['route']}
    def classify(self,text,*,classification='PRIVATE',reference=None):
        if classification in BLOCKED_EXTERNAL_CLASSIFICATIONS and not self.allow_external_sensitive:raise PermissionError('classification prohibits external advisory safety transmission')
        if self.classifier is not None:
            result=self.classifier(text);provenance={'provider':'injected','model':'injected','capability':'safety','fallback':False,'provider_request_id':None}
        elif self.model_manager is not None:
            routed=self.model_manager.assess_safety(text);result=dict(routed['assessment']);provenance=dict(routed['provenance'])
        else:raise RuntimeError('external_dependency:safety_model')
        if not isinstance(result,dict) or result.get('label') not in {'safe','unsafe','flagged'} or not isinstance(result.get('flagged',result.get('label')!='safe'),bool):raise RuntimeError('invalid_safety_model_result')
        result['flagged']=bool(result.get('flagged',result['label']!='safe'))
        record={'advisory_id':'safety_'+uuid.uuid4().hex,'reference':reference,'provider':provenance.get('provider'),'model':provenance.get('model'),'provider_request_id':provenance.get('provider_request_id'),'fallback':bool(provenance.get('fallback',False)),'classification':classification,'label':result['label'],'flagged':result['flagged'],'advisory_result':{'label':result['label'],'flagged':result['flagged'],'details':result.get('details',{})},'timestamp':datetime.now(UTC).isoformat(),'authoritative':False}
        if self.store is not None:self.store.save_safety_advisory(record)
        return record
