import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

from sparkle.secrets import SecretResolver,SecretNotFoundError
from sparkle_gen2.model_manager import ModelCapabilityManager,build_gen2_model_registry
from sparkle_gen2.nvidia_models import NVIDIAVoiceChatAdapter
from sparkle_gen2.protected_secrets import VOICECHAT_SECRET_REF,build_gen2_secret_resolver,protected_voicechat_environment
from sparkle_gen2.voice_runtime import INPUT_RATE,OUTPUT_RATE,VoiceSessionService
from sparkle_gen2.storage import Gen2Store

class Cycle71VoiceChatTests(unittest.TestCase):
    def registry_path(self):return Path(__file__).parents[1]/'src/sparkle_gen2/nemotron_models.json'
    def make_env(self,root,content,mode=0o600):
        p=Path(root)/'gen2.env';p.write_text(content);p.chmod(mode);return p

    def test_protected_voicechat_reference_loads_from_owner_only_config(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_env(d,"NEMOTRON_VOICECHAT_API_KEY='unit-secret-value'\nNVIDIA_API_KEY='must-not-load'\n")
            env,status=protected_voicechat_environment(base={},path=p)
            self.assertTrue(status.credential_reference_found);self.assertTrue(status.credential_file_exists);self.assertEqual(status.credential_permissions,'0o600');self.assertTrue(status.credential_value_loaded);self.assertTrue(status.secure_permissions);self.assertTrue(status.owner_matches)
            self.assertEqual(set(env),{VOICECHAT_SECRET_REF});self.assertNotIn('NVIDIA_API_KEY',env)
            resolver=build_gen2_secret_resolver(base={},path=p);self.assertTrue(resolver.status([VOICECHAT_SECRET_REF])[VOICECHAT_SECRET_REF])

    def test_insecure_config_is_not_parsed(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_env(d,'NEMOTRON_VOICECHAT_API_KEY=do-not-load\n',0o644)
            env,status=protected_voicechat_environment(base={},path=p)
            self.assertFalse(status.secure_permissions);self.assertFalse(status.credential_reference_found);self.assertFalse(status.credential_value_loaded);self.assertNotIn(VOICECHAT_SECRET_REF,env)
            with self.assertRaises(SecretNotFoundError):build_gen2_secret_resolver(base={},path=p).first([VOICECHAT_SECRET_REF])

    def test_environment_value_precedence_and_no_global_environment_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_env(d,'NEMOTRON_VOICECHAT_API_KEY=file-value\n')
            before=dict(os.environ);env,status=protected_voicechat_environment(base={VOICECHAT_SECRET_REF:'process-value'},path=p)
            self.assertEqual(env[VOICECHAT_SECRET_REF],'process-value');self.assertTrue(status.credential_value_loaded);self.assertEqual(dict(os.environ),before)

    def test_unknown_secrets_are_never_imported_from_protected_file(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_env(d,'UNRELATED_SECRET=private\nNVIDIA_API_KEY=private2\nNEMOTRON_VOICECHAT_API_KEY=voice-only\n')
            env,_=protected_voicechat_environment(base={},path=p);self.assertEqual(set(env),{VOICECHAT_SECRET_REF})

    def test_voice_registry_contract_remains_transport_gated(self):
        data=json.loads(self.registry_path().read_text());v=next(x for x in data['models'] if x['id']=='nvidia-nemotron-voicechat')
        self.assertEqual(v['provider'],'nvidia');self.assertEqual(v['model_id'],'nvidia/nemotron-voicechat');self.assertEqual(v['secret_refs'],[VOICECHAT_SECRET_REF]);self.assertTrue(v['requires_verified_transport']);self.assertFalse(v['transport_verified']);self.assertEqual(v['transport_kind'],'nvidia_build_realtime_observed');self.assertFalse(v['allow_fallback']);self.assertEqual(v['health_path'],'/v1/realtime/health');self.assertNotIn('base_url',v);self.assertEqual(v['websocket_url'],'wss://api.ngc.nvidia.com/v2/predict/artifactname/websocket/v1/realtime?nv-function-id=42c86b5f-545a-4b2f-a83b-90fd71da9912');self.assertNotIn('inference_url',v)
        self.assertEqual(v['input_audio']['sample_rate_hz'],24000);self.assertEqual(v['output_audio']['sample_rate_hz'],24000);self.assertEqual((INPUT_RATE,OUTPUT_RATE),(24000,24000))

    def test_secure_credential_configures_adapter_but_does_not_enable_unverified_transport(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_env(d,'NEMOTRON_VOICECHAT_API_KEY=unit-secret\n')
            resolver=build_gen2_secret_resolver(base={},path=p);r=build_gen2_model_registry(path=self.registry_path(),secrets=resolver);a=r.adapter('nvidia-nemotron-voicechat');h=a.health();self.assertTrue(h['configured']);self.assertFalse(h['transport_verified'])
            m=ModelCapabilityManager(registry=r,fallback_allowed=False);self.assertIsNone(m.route(['voice'],input_modalities=['audio'],output_modalities=['audio','text']).selected);self.assertEqual(m.status('voice')['status'],'EXTERNALLY_BLOCKED')

    def test_explicit_secret_resolver_is_not_replaced(self):
        resolver=SecretResolver({VOICECHAT_SECRET_REF:'explicit-test'});r=build_gen2_model_registry(path=self.registry_path(),secrets=resolver);self.assertIs(r.secrets,resolver)

    def test_production_adapter_refuses_session_without_verified_transport(self):
        cfg=next(x for x in json.loads(self.registry_path().read_text())['models'] if x['id']=='nvidia-nemotron-voicechat')
        a=NVIDIAVoiceChatAdapter(cfg,SecretResolver({VOICECHAT_SECRET_REF:'test-only'}))
        self.assertTrue(a.health()['configured']);self.assertFalse(a.health()['transport_verified'])
        with self.assertRaisesRegex(Exception,'streaming transport is not verified'):
            a.open_session({'session_id':'s'})

    def test_voice_service_health_stays_unavailable_without_real_transport(self):
        r=build_gen2_model_registry(path=self.registry_path(),secrets=SecretResolver({VOICECHAT_SECRET_REF:'test-only'}));m=ModelCapabilityManager(registry=r,fallback_allowed=False)
        with tempfile.TemporaryDirectory() as d:
            svc=VoiceSessionService(Gen2Store(Path(d)/'g.db'),model_manager=m);h=svc.health();self.assertEqual(h['status'],'UNAVAILABLE');self.assertFalse(h['live_verified'])

    def test_cycle71_files_do_not_embed_secret_values_or_add_transport_guess(self):
        paths=[Path('src/sparkle_gen2/infrastructure/security/protected_secrets.py'),Path('src/sparkle_gen2/infrastructure/providers/model_manager.py')]
        blob='\n'.join(p.read_text() for p in paths)
        self.assertNotIn('wss'+ '://',blob);self.assertNotIn('Authorization'+': Bearer',blob);self.assertNotIn('shell'+'=True',blob);self.assertNotIn('subprocess'+'.',blob)
        self.assertIn(VOICECHAT_SECRET_REF,blob)

if __name__=='__main__':unittest.main()
