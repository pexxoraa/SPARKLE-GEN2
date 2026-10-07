import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from sparkle_gen2.gen1 import LocalGen1Gateway, _canonical_skill_levels

class FinalGen1SafetyAcceptanceTests(unittest.TestCase):
    def test_native_tool_exception_is_secret_safe(self):
        gateway=LocalGen1Gateway.__new__(LocalGen1Gateway)
        tools=Mock();tools.names={'calculator'}
        tools.execute.side_effect=ValueError('api_key=private-acceptance-canary')
        gateway.system=SimpleNamespace(tools=tools)
        result=gateway.invoke('calculator',{'expression':'2+2'})
        self.assertFalse(result.ok)
        self.assertFalse(result.verification['verified'])
        self.assertEqual(result.output['error_type'],'ValueError')
        self.assertNotIn('private-acceptance-canary',json.dumps(result.output))
    def test_gen2_skill_level_labels_cover_zero_through_six_without_inflating_evidence(self):
        source={'matches':[{'current_level':n,'current_level_name':'native-label','verified_evidence_count':n} for n in range(7)]}
        output=_canonical_skill_levels(source)
        self.assertEqual([x['current_level_name'] for x in output['matches']],['UNKNOWN','AWARENESS','BEGINNER','WORKING','COMPETENT','ADVANCED','MASTERED'])
        self.assertEqual([x['current_level'] for x in output['matches']],list(range(7)))
        self.assertEqual([x['verified_evidence_count'] for x in output['matches']],list(range(7)))
        self.assertTrue(all(x['source_level_name']=='native-label' for x in output['matches']))
        self.assertTrue(all(x['current_level_name']=='native-label' for x in source['matches']))
    def test_skill_tool_observation_uses_gen2_labels_without_mutating_native_response(self):
        gateway=LocalGen1Gateway.__new__(LocalGen1Gateway)
        tools=Mock();tools.names={'skill_search'};output={'matches':[{'current_level':0,'current_level_name':'awareness','verified_evidence_count':0}]};tools.execute.return_value=output
        gateway.system=SimpleNamespace(tools=tools)
        observed=gateway.invoke('skill_search',{'query':'arithmetic'})
        self.assertTrue(observed.verification['verified'])
        self.assertEqual(observed.output['matches'][0]['current_level_name'],'UNKNOWN')
        self.assertEqual(output['matches'][0]['current_level_name'],'awareness')
