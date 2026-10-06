"""Resource limits use persistent measured usage; unknown token costs fail closed."""
from __future__ import annotations
from dataclasses import dataclass,field


@dataclass(frozen=True,slots=True)
class ResourceBudget:
    limits:dict[str,float]=field(default_factory=dict)

    def __post_init__(self):
        import math
        if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or v<=0 for v in self.limits.values()):raise ValueError('invalid_resource_limit')

    def check(self, usage, *, reservations=None):
        for resource,limit in self.limits.items():
            measured=usage.get(resource)
            if measured is None:return {'allowed':False,'resource':resource,'reason':'usage_unavailable'}
            if measured+(reservations or {}).get(resource,0)>limit or (not reservations and measured>=limit):
                return {'allowed':False,'resource':resource,'reason':'resource_budget_exhausted'}
        return {'allowed':True}

    @staticmethod
    def usage(runs):
        result={'tool_calls':0,'runtime_seconds':0.0,'planning_calls':0,'reported_tokens':0}
        known=True
        for run in runs:
            result['tool_calls']+=int(run.get('iterations',0));result['runtime_seconds']+=float(run.get('active_runtime_seconds',0))
            usage=run.get('resource_usage') or {};result['planning_calls']+=int(usage.get('planning_calls',0))
            if usage.get('planning_calls') and 'reported_tokens' not in usage:known=False
            result['reported_tokens']+=int(usage.get('reported_tokens',0))
        if not known:result['reported_tokens']=None
        return result
