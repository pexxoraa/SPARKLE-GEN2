"""Evaluate explicit step criteria after independently observed adapter evidence."""
from __future__ import annotations
from typing import Callable


class StepVerifier:
    TYPES={'returned_value','expected_state','http_status','file_exists','database_state',
           'command_result','test_result','artifact_exists','semantic','custom'}

    def __init__(self):self._custom:dict[str,Callable]={}

    def register(self, name, verifier):
        if not name or name in self._custom or not callable(verifier):raise ValueError('invalid_verifier_registration')
        self._custom[name]=verifier

    @classmethod
    def validate(cls, strategy):
        if not isinstance(strategy,dict):raise ValueError('invalid_verification_strategy')
        if not strategy:return
        if strategy.get('type') not in cls.TYPES:raise ValueError('unsupported_step_verification')
        if strategy.get('type') in {'returned_value','expected_state','database_state','http_status','file_exists','command_result','test_result','artifact_exists'}:
            if not isinstance(strategy.get('path'),str) or not strategy['path'] or len(strategy['path'])>200:raise ValueError('verification_path_required')
        if strategy.get('type') in {'returned_value','expected_state','database_state'} and 'expected' not in strategy:raise ValueError('verification_expected_required')
        if strategy.get('type') in {'semantic','custom'} and not isinstance(strategy.get('verifier'),str):raise ValueError('custom_verifier_required')

    @staticmethod
    def _value(data, path):
        for key in path.split('.'):
            if isinstance(data,dict):data=data[key]
            elif isinstance(data,list) and key.isdigit():data=data[int(key)]
            else:raise KeyError('verification_path_missing')
        return data

    def verify(self, step, observation):
        evidence=dict(observation.verification)
        # Native approval proposals are not effects; the approval reconciler owns them.
        if observation.requires_approval or not observation.ok or evidence.get('verified') is not True:return evidence
        strategy=step.verification_strategy
        if not strategy:return evidence
        kind=strategy['type'];passed=False;reason='criterion_mismatch'
        try:
            if kind in {'semantic','custom'}:
                verifier=self._custom.get(strategy['verifier'])
                if verifier is None:reason='verifier_unavailable'
                else:passed=verifier(step,observation,strategy) is True
            else:
                value=self._value(observation.output,strategy['path'])
                if kind in {'returned_value','expected_state','database_state'}:passed=type(value) is type(strategy['expected']) and value==strategy['expected']
                elif kind=='http_status':passed=isinstance(value,int) and not isinstance(value,bool) and value in strategy.get('accepted',[200])
                elif kind in {'file_exists','test_result'}:passed=value is True if kind=='file_exists' else value in ('passed','COMPLETED',True)
                elif kind=='command_result':passed=isinstance(value,int) and not isinstance(value,bool) and value==0
                elif kind=='artifact_exists':passed=bool(value) and isinstance(value,(str,int))
        except (KeyError,IndexError,TypeError,ValueError):reason='verification_evidence_missing'
        return {**evidence,'verified':passed,'method':'adapter observation + '+kind,
                'criteria':{'type':kind,'path':strategy.get('path'),'passed':passed},'reason':None if passed else reason}
