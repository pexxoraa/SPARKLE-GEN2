"""Regression evidence from the October 7 final live API/security audit."""
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

from sparkle_gen2.device_identity import DeviceIdentityService
from sparkle_gen2.interfaces.http.transport import JsonRequest
from sparkle_gen2.personal_core import build_server
from sparkle_gen2.storage import Gen2Store


def body(raw=b'{}', **headers):
    msg = Message()
    for key, value in headers.items():
        msg[key.replace('_', '-')] = str(value)
    return SimpleNamespace(headers=msg, rfile=io.BytesIO(raw))


class FinalHttpParserTests(unittest.TestCase):
    def test_empty_body_and_valid_chunk_extensions(self):
        self.assertEqual(JsonRequest.read(body(b'', Content_Length=0)), {})
        self.assertEqual(JsonRequest.read(body(b'2;extension=ok\r\n{}\r\n0\r\nX-Audit: ok\r\n\r\n', Transfer_Encoding='chunked')), {})

    def test_chunk_size_is_bounded_unsigned_hex(self):
        for size in (b'-1', b'+2', b'0x2', b'fffffffffffffffff', b'bad!' , b' 2'):
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, 'invalid_chunk_size'):
                JsonRequest.read(body(size + b'\r\n{}\r\n0\r\n\r\n', Transfer_Encoding='chunked'))

    def test_oversized_lines_trailers_and_chunk_count(self):
        cases = [b'2;' + b'x' * 9000 + b'\r\n', b'0\r\n' + (b'X: ' + b'x' * 7000 + b'\r\n') * 3 + b'\r\n', b'1\r\nx\r\n' * 4097 + b'0\r\n\r\n']
        for raw in cases:
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                JsonRequest.read(body(raw, Transfer_Encoding='chunked'))

    def test_framing_is_unambiguous(self):
        for headers in ({'Transfer_Encoding': 'chunked', 'Content_Length': 2}, {'Transfer_Encoding': 'gzip, chunked'}, {'Content_Length': '-1'}, {'Content_Length': '+2'}):
            with self.subTest(headers=headers), self.assertRaises(ValueError):
                JsonRequest.read(body(b'{}', **headers))
        h = body(b'{}', Content_Length=2)
        h.headers['Content-Length'] = '2'
        with self.assertRaisesRegex(ValueError, 'ambiguous_request_framing'):
            JsonRequest.read(h)

    def test_errors_do_not_echo_raw_body(self):
        for raw in (b'{"token":"private-test-token",', b'\xff', b'[]'):
            with self.subTest(raw=raw), self.assertRaises(ValueError) as raised:
                JsonRequest.read(body(raw, Content_Length=len(raw)))
            self.assertNotIn('private-test-token', str(raised.exception))

    def test_structure_numbers_and_content_type(self):
        for value in ({'number': float('nan')}, {'number': float('inf')}, {'items': [0] * 10001}):
            raw = json.dumps(value).encode()
            with self.subTest(value_type=type(value)), self.assertRaises(ValueError):
                JsonRequest.read(body(raw, Content_Length=len(raw)))
        value = 'leaf'
        for _ in range(25):
            value = {'nested': value}
        raw = json.dumps(value).encode()
        with self.assertRaisesRegex(ValueError, 'json_structure_too_large'):
            JsonRequest.read(body(raw, Content_Length=len(raw)))
        with self.assertRaisesRegex(ValueError, 'json_content_type_required'):
            JsonRequest.read(body(b'{}', Content_Length=2, Content_Type='text/plain'))

    def test_public_types_fail_before_services(self):
        for value in ({'units': 7}, {'metadata': 7}, {'model_id': []}, {'max_iterations': True}, {'supported': 'false'}, {'capabilities': ['conversation', {}]}, {'time_budget_seconds': -1}):
            with self.subTest(field=next(iter(value))), self.assertRaisesRegex(ValueError, 'invalid_field_type'):
                JsonRequest.validate_fields(value)
        JsonRequest.validate_fields({'units': [], 'metadata': {}, 'model_id': None, 'max_iterations': 3, 'supported': False, 'priority': 5, 'time_budget_seconds': 0.5})


class FinalHttpLiveContractTests(unittest.TestCase):
    def test_authenticated_malformed_routes_and_cross_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Gen2Store(Path(directory) / 'audit.db')
            devices = DeviceIdentityService(store)
            code = devices.create_enrollment_code()['code']
            _, token = devices.enroll(code, name='Audit', kind='laptop', os_name='Linux', capabilities=['conversation', 'task_status', 'artifacts'])
            core = SimpleNamespace(store=store, devices=devices)
            server = build_server(core, '127.0.0.1', 0)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f'http://127.0.0.1:{server.server_address[1]}'
            try:
                cases = [('/api/os/learning', {'units': 7}), ('/api/os/records', {'metadata': 7}), ('/api/conversation/model', {'model_id': []}), ('/api/background', {'max_iterations': {}}), ('/api/voice/sessions', {'persist_transcript': 'false'})]
                for path, value in cases:
                    with self.subTest(path=path):
                        request = urllib.request.Request(base + path, data=json.dumps(value).encode(), headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
                        with self.assertRaises(urllib.error.HTTPError) as raised:
                            urllib.request.urlopen(request, timeout=3)
                        with raised.exception as error:
                            self.assertEqual(error.code, 400)
                            self.assertTrue(json.loads(error.read())['error'].startswith('invalid_field_type:'))
                for path in ('/api/events?limit=private-test-token', '/api/events?after=private-test-token', '/api/artifacts/private-test-token/download'):
                    with self.subTest(path=path):
                        request = urllib.request.Request(base + path, headers={'Authorization': 'Bearer ' + token})
                        with self.assertRaises(urllib.error.HTTPError) as raised:
                            urllib.request.urlopen(request, timeout=3)
                        with raised.exception as error:
                            self.assertEqual(error.code, 400)
                            value=json.loads(error.read())
                            self.assertEqual(value['error'], 'invalid_request')
                            self.assertNotIn('private-test-token', str(value))
                request = urllib.request.Request(base + '/api/logout', data=b'{}', headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'Origin': 'https://untrusted.example'})
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=3)
                with raised.exception as error:
                    self.assertEqual(error.code, 403)
                    self.assertEqual(json.loads(error.read())['error'], 'cross_origin_request_denied')
                self.assertEqual(store.recent_goals(10), [])
            finally:
                server.shutdown()
                server.server_close()
