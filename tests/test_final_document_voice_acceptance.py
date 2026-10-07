import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sparkle_gen2.document_intelligence import DocumentIntelligenceService
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.voice_runtime import VoiceInputFrame, VoiceSessionService
from sparkle_gen2.core_time import now
from test_cycle53_document_intelligence import write_xlsx, zwrite
from test_cycle61_voice_integration import SessionAwareTransport


class FinalDocumentVoiceAcceptanceTests(unittest.TestCase):
    def test_markdown_uses_bounded_text_pipeline_with_persisted_retrieval(self):
        with tempfile.TemporaryDirectory() as directory:
            for extension in ('.md', '.markdown'):
                with self.subTest(extension=extension):
                    path = Path(directory) / ('robotics' + extension)
                    path.write_text('# Calibration\n\nVerify emergency stop before motion.\n', encoding='utf-8')
                    store = Gen2Store(Path(directory) / 'documents.db')
                    service = DocumentIntelligenceService(store, allowed_roots=[directory])
                    record = service.ingest_path(path, user_id='alice', classification='PUBLIC')
                    self.assertEqual(record.status, 'READY')
                    self.assertEqual(record.media_type, 'text/markdown')
                    self.assertTrue(record.provenance['local_only_extraction'])
                    restarted = DocumentIntelligenceService(Gen2Store(store.path), allowed_roots=[directory])
                    result = restarted.search('emergency stop', user_id='alice', document_id=record.document_id)
                    self.assertTrue(result['verified'])
                    self.assertIn('Verify emergency stop', result['items'][0]['text'])
    def test_xlsx_inline_strings_and_absolute_package_relationships_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'inline.xlsx'
            write_xlsx(path)
            import zipfile
            with zipfile.ZipFile(path) as archive:
                files = {name: archive.read(name).decode() for name in archive.namelist()}
            files['xl/_rels/workbook.xml.rels'] = files['xl/_rels/workbook.xml.rels'].replace('Target="worksheets/', 'Target="/xl/worksheets/')
            files['xl/worksheets/sheet1.xml'] = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Task</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><r><t>Calibrate </t></r><r><t>arm</t></r></is></c></row></sheetData></worksheet>'
            zwrite(path, files)
            service = DocumentIntelligenceService(Gen2Store(Path(directory) / 'documents.db'), allowed_roots=[directory])
            record = service.ingest_path(path, user_id='alice')
            self.assertEqual(record.status, 'READY')
            self.assertEqual(record.structured_content['sheets'][0]['headers'], ['Task'])
            self.assertEqual(record.structured_content['sheets'][0]['rows'][1]['cells'][0]['value'], 'Calibrate arm')
            self.assertIn('Calibrate arm', service.search('calibrate', user_id='alice')['items'][0]['text'])
    def test_extraction_provider_exception_text_is_not_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'note.txt'
            path.write_text('Own synthetic note')
            service = DocumentIntelligenceService(Gen2Store(Path(directory) / 'documents.db'), allowed_roots=[directory])
            with patch.object(service, '_extract', side_effect=RuntimeError('api_key=private-acceptance-canary')):
                record = service.ingest_path(path, user_id='alice')
            self.assertEqual(record.status, 'FAILED')
            self.assertNotIn('private-acceptance-canary', json.dumps(service.get(record.document_id, user_id='alice').to_dict()))
    def test_voice_provider_exception_text_is_not_persisted_or_raised(self):
        with tempfile.TemporaryDirectory() as directory:
            for phase in ('connect', 'input', 'tts'):
                with self.subTest(phase=phase):
                    transport = SessionAwareTransport()
                    service = VoiceSessionService(Gen2Store(Path(directory) / (phase + '.db')), provider=transport)
                    session = service.create()
                    exc = RuntimeError('api_key=private-acceptance-canary')
                    if phase == 'connect':
                        with patch.object(transport, 'open_session', side_effect=exc):
                            self.assertEqual(service.connect(session.session_id).state, 'FAILED')
                    else:
                        service.connect(session.session_id)
                        if phase == 'input':
                            with patch.object(transport, 'send_audio', side_effect=exc), self.assertRaises(RuntimeError) as raised:
                                service.push(VoiceInputFrame(session.session_id, 0, b'\x00\x00', now(), final=True))
                        else:
                            with patch.object(transport, 'respond_text', side_effect=exc), self.assertRaises(RuntimeError) as raised:
                                service._authorized_speech(service._load(session.session_id), transport, {'text':'Authorized synthetic response','status':'COMPLETED'}, [], {})
                        self.assertNotIn('private-acceptance-canary', str(raised.exception))
                    self.assertNotIn('private-acceptance-canary', json.dumps(service.store.load_voice_session(session.session_id).to_dict()))
                    self.assertNotIn('private-acceptance-canary', json.dumps(service.store.voice_events(session.session_id)))
    def test_voice_input_failure_does_not_claim_task_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            service = VoiceSessionService(Gen2Store(Path(directory) / 'voice.db'), provider=SessionAwareTransport(fail_send=True))
            session = service.create(); service.connect(session.session_id)
            result = service.push(VoiceInputFrame(session.session_id, 0, b'\x00\x00', now(), final=True))
            self.assertEqual(result.agent_result['status'], 'FAILED')
            self.assertTrue(result.agent_result['voice_retry'])
            self.assertIsNone(service.store.load_voice_session(session.session_id).outcome)
    def test_voice_dispatch_failure_does_not_replay_or_claim_task_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            conversations = Mock()
            conversations._looks_like_knowledge_question.return_value = False
            conversations.send.side_effect = RuntimeError('synthetic failure')
            service = VoiceSessionService(Gen2Store(Path(directory) / 'voice.db'), provider=SessionAwareTransport(transcript='calculate 2+2'), conversation_service=conversations)
            session = service.create(); service.connect(session.session_id)
            result = service.push(VoiceInputFrame(session.session_id, 0, b'\x00\x00', now(), final=True))
            self.assertEqual(result.agent_result['status'], 'FAILED')
            self.assertTrue(result.agent_result['voice_retry'])
            self.assertEqual(conversations.send.call_count, 1)
