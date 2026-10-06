"""Explicit model-selection constraints; unknown cost/quality metadata fails closed."""
from __future__ import annotations
import math

CLASSES={'PUBLIC','PERSONAL','SENSITIVE','SECRET','SYSTEM'}
COMPLEXITY={'simple':1,'standard':2,'complex':3}

def selection_metadata(config):
    if not isinstance(config,dict):raise ValueError('invalid_model_selection_metadata')
    location=config.get('execution_location','unknown')
    if not isinstance(location,str) or location not in {'local','remote','unknown'}:raise ValueError('invalid_model_location')
    privacy=config.get('privacy_classifications',['PUBLIC','PERSONAL'])
    if not isinstance(privacy,list) or not privacy or any(not isinstance(x,str) or x not in CLASSES for x in privacy):raise ValueError('invalid_model_privacy_metadata')
    cost=config.get('cost_per_million_tokens')
    if cost is not None and (isinstance(cost,bool) or not isinstance(cost,(int,float)) or not math.isfinite(cost) or cost<0):raise ValueError('invalid_model_cost_metadata')
    complexity=config.get('max_task_complexity')
    if complexity is not None and (not isinstance(complexity,str) or complexity not in COMPLEXITY):raise ValueError('invalid_model_complexity_metadata')
    return {'execution_location':location,'privacy_classifications':privacy,'cost_per_million_tokens':cost,'max_task_complexity':complexity}

def validate_constraints(value):
    if value is None:return {}
    if not isinstance(value,dict) or set(value)-{'execution_location','classification','max_cost_per_million_tokens','task_complexity','latency_class'}:raise ValueError('invalid_model_constraints')
    if 'execution_location' in value and (not isinstance(value['execution_location'],str) or value['execution_location'] not in {'local','remote'}):raise ValueError('invalid_model_location_constraint')
    if 'classification' in value and (not isinstance(value['classification'],str) or value['classification'] not in CLASSES):raise ValueError('invalid_model_classification')
    if 'task_complexity' in value and (not isinstance(value['task_complexity'],str) or value['task_complexity'] not in COMPLEXITY):raise ValueError('invalid_task_complexity')
    if 'latency_class' in value and (not isinstance(value['latency_class'],str) or value['latency_class'] not in {'fast','balanced','deep'}):raise ValueError('invalid_model_latency_constraint')
    if 'max_cost_per_million_tokens' in value:
        cost=value['max_cost_per_million_tokens']
        if isinstance(cost,bool) or not isinstance(cost,(int,float)) or not math.isfinite(cost) or cost<0:raise ValueError('invalid_model_cost_constraint')
    return dict(value)

def permits(record,constraints):
    meta=record.provenance.get('selection_policy') or selection_metadata({})
    if constraints.get('classification')=='SECRET':return False
    if 'classification' in constraints and constraints['classification'] not in meta['privacy_classifications']:return False
    if 'execution_location' in constraints and constraints['execution_location']!=meta['execution_location']:return False
    if 'latency_class' in constraints and constraints['latency_class']!=record.latency_class:return False
    if 'max_cost_per_million_tokens' in constraints:
        cost=meta['cost_per_million_tokens']
        if cost is None or cost>constraints['max_cost_per_million_tokens']:return False
    if 'task_complexity' in constraints:
        supported=meta['max_task_complexity']
        if supported is None or COMPLEXITY[supported]<COMPLEXITY[constraints['task_complexity']]:return False
    return True
