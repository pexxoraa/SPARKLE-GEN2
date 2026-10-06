import base64
import json
import unittest
from types import SimpleNamespace

from sparkle.secrets import SecretResolver
from sparkle_gen2.nvidia_voicechat_transport import (
    CLIENT_SAMPLE_RATE,
    NVIDIAHostedVoiceChatTransport,
    PERSONAL_AGENT_TOOL,
    hosted_voicechat_url,
    validate_hosted_voicechat_url,
)


class FakeWebSocket:
    def __init__(self, events):
        self.events = list(events)
        self.sent = []
        self.closed = False

    def recv(self, timeout=None):
        if not self.events:
            raise TimeoutError("empty")
        value = self.events.pop(0)
        return value if isinstance(value, str) else json.dumps(value)

    def send(self, value):
        self.sent.append(json.loads(value))

    def close(self):
        self.closed = True


class Connector:
    def __init__(self, websocket):
        self.websocket = websocket
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.websocket


def created():
    return {
        "type": "session.created",
        "event_id": "created",
        "session": {
            "id": "provider-session",
            "audio": {
                "input": {"format": {"type": "audio/pcm", "rate": 24000}},
                "output": {"format": {"type": "audio/pcm", "rate": 24000}},
            },
        },
    }


def updated():
    return {
        "type": "session.updated",
        "event_id": "updated",
        "session": {
            "audio": {
                "input": {"format": {"type": "audio/pcm", "rate": 24000}},
                "output": {"format": {"type": "audio/pcm", "rate": 24000}},
            },
            "tools": [{"type": "function", "name": PERSONAL_AGENT_TOOL}],
            "tool_choice": "required",
        },
    }


class HostedVoiceChatTransportTests(unittest.TestCase):
    function_id = "42c86b5f-545a-4b2f-a83b-90fd71da9912"

    def transport(self, events):
        ws = FakeWebSocket(events)
        connector = Connector(ws)
        transport = NVIDIAHostedVoiceChatTransport(
            function_id=self.function_id,
            secrets=SecretResolver({"NEMOTRON_VOICECHAT_API_KEY": "unit-secret"}),
            secret_refs=["NEMOTRON_VOICECHAT_API_KEY"],
            connector=connector,
            event_timeout=0.1,
            turn_timeout=0.2,
        )
        return transport, ws, connector

    def session_contract(self):
        return {
            "session_id": "sparkle-session",
            "input_audio": {
                "sample_rate": CLIENT_SAMPLE_RATE,
                "channels": 1,
                "sample_width": 2,
                "encoding": "pcm_s16le",
            },
            "output_audio": {
                "sample_rate": CLIENT_SAMPLE_RATE,
                "channels": 1,
                "sample_width": 2,
                "encoding": "pcm_s16le",
            },
        }

    def test_endpoint_is_exact_tls_build_gateway(self):
        url = hosted_voicechat_url(self.function_id)
        self.assertTrue(url.startswith("wss://api.ngc.nvidia.com/"))
        self.assertEqual(validate_hosted_voicechat_url(url, self.function_id), url)
        for bad in (
            url.replace("wss://", "ws://"),
            url.replace("api.ngc.nvidia.com", "evil.example"),
            url + "&x=1",
            url.replace(self.function_id, "00000000-0000-0000-0000-000000000000"),
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_hosted_voicechat_url(bad, self.function_id)

    def test_open_session_pins_auth_to_exact_gateway_and_negotiates_24khz(self):
        transport, ws, connector = self.transport([created(), updated()])
        ref = transport.open_session(self.session_contract())
        self.assertTrue(ref.startswith("nvcf_"))
        self.assertEqual(len(connector.calls), 1)
        url, kwargs = connector.calls[0]
        self.assertEqual(url, hosted_voicechat_url(self.function_id))
        self.assertEqual(set(kwargs["additional_headers"]), {"Authorization"})
        self.assertNotIn("unit-secret", json.dumps(ws.sent))
        event = ws.sent[0]
        self.assertEqual(event["type"], "session.update")
        self.assertEqual(event["session"]["audio"]["input"]["format"]["rate"], 24000)
        self.assertEqual(event["session"]["audio"]["output"]["format"]["rate"], 24000)
        self.assertEqual(event["session"]["tool_choice"], "required")
        self.assertEqual(event["session"]["tools"][0]["name"], PERSONAL_AGENT_TOOL)

    def test_provider_audio_is_buffered_and_never_exposed_before_personalagent(self):
        audio = base64.b64encode(b"\x00\x00" * 40).decode()
        events = [
            created(),
            updated(),
            {"type": "response.output_audio.delta", "event_id": "a", "delta": audio},
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "event_id": "t",
                "item_id": "u1",
                "transcript": "calculate two plus two",
            },
            {
                "type": "response.function_call_arguments.done",
                "event_id": "f",
                "call_id": "call1",
                "name": PERSONAL_AGENT_TOOL,
                "arguments": json.dumps({"request": "calculate two plus two"}),
            },
        ]
        transport, _, _ = self.transport(events)
        ref = transport.open_session(self.session_contract())
        frame = SimpleNamespace(
            sample_rate=24000,
            channels=1,
            sample_width=2,
            encoding="pcm_s16le",
            audio=b"\x00\x00" * 40,
            final=True,
        )
        result = transport.send_audio(ref, frame)
        self.assertEqual(result["audio_chunks"], [])
        self.assertEqual(result["transcripts"][0]["speaker"], "user")
        self.assertGreater(result["pre_authorization_audio_bytes"], 0)

    def test_final_user_transcript_without_personalagent_delegation_fails_closed(self):
        events = [
            created(),
            updated(),
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "event_id": "t",
                "item_id": "u1",
                "transcript": "hello",
            },
        ]
        transport, _, _ = self.transport(events)
        ref = transport.open_session(self.session_contract())
        frame = SimpleNamespace(
            sample_rate=24000,
            channels=1,
            sample_width=2,
            encoding="pcm_s16le",
            audio=b"\x00\x00" * 40,
            final=True,
        )
        with self.assertRaises(PermissionError):
            transport.send_audio(ref, frame)

    def test_function_name_and_arguments_cannot_widen_authority(self):
        for event in (
            {
                "type": "response.function_call_arguments.done",
                "event_id": "f",
                "call_id": "call1",
                "name": "shell",
                "arguments": "{}",
            },
            {
                "type": "response.function_call_arguments.done",
                "event_id": "f",
                "call_id": "call1",
                "name": PERSONAL_AGENT_TOOL,
                "arguments": json.dumps({"request": "x", "approved": True}),
            },
        ):
            with self.subTest(event=event):
                events = [
                    created(),
                    updated(),
                    {
                        "type": "conversation.item.input_audio_transcription.completed",
                        "event_id": "t",
                        "item_id": "u1",
                        "transcript": "test",
                    },
                    event,
                ]
                transport, _, _ = self.transport(events)
                ref = transport.open_session(self.session_contract())
                frame = SimpleNamespace(
                    sample_rate=24000,
                    channels=1,
                    sample_width=2,
                    encoding="pcm_s16le",
                    audio=b"\x00\x00" * 40,
                    final=True,
                )
                with self.assertRaises(PermissionError):
                    transport.send_audio(ref, frame)

    def test_personalagent_result_is_returned_as_function_output_before_audio_release(self):
        audio = base64.b64encode(b"\x01\x00" * 40).decode()
        events = [
            created(),
            updated(),
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "event_id": "t",
                "item_id": "u1",
                "transcript": "calculate two plus two",
            },
            {
                "type": "response.function_call_arguments.done",
                "event_id": "f",
                "call_id": "call1",
                "name": PERSONAL_AGENT_TOOL,
                "arguments": json.dumps({"request": "calculate two plus two"}),
            },
            {"type": "response.created", "event_id": "r", "response": {"id": "r1"}},
            {
                "type": "response.output_audio.delta",
                "event_id": "a",
                "response_id": "r1",
                "delta": audio,
            },
            {
                "type": "response.output_audio_transcript.done",
                "event_id": "d",
                "response_id": "r1",
                "transcript": "The verified result is four.",
            },
        ]
        transport, ws, _ = self.transport(events)
        ref = transport.open_session(self.session_contract())
        frame = SimpleNamespace(
            sample_rate=24000,
            channels=1,
            sample_width=2,
            encoding="pcm_s16le",
            audio=b"\x00\x00" * 40,
            final=True,
        )
        transport.send_audio(ref, frame)
        result = transport.respond_text(ref, "The verified result is four.")
        self.assertTrue(result["audio_chunks"])
        function_outputs = [
            x for x in ws.sent if x.get("type") == "conversation.item.create"
        ]
        self.assertEqual(len(function_outputs), 1)
        item = function_outputs[0]["item"]
        self.assertEqual(item["type"], "function_call_output")
        self.assertEqual(item["call_id"], "call1")
        payload = json.loads(item["output"])
        self.assertEqual(payload["status"], "COMPLETED")

    def test_malformed_or_unknown_event_fails_closed(self):
        events = [created(), updated(), {"type": "provider.magic", "event_id": "x"}]
        transport, _, _ = self.transport(events)
        ref = transport.open_session(self.session_contract())
        frame = SimpleNamespace(
            sample_rate=24000,
            channels=1,
            sample_width=2,
            encoding="pcm_s16le",
            audio=b"\x00\x00" * 40,
            final=True,
        )
        with self.assertRaises(Exception):
            transport.send_audio(ref, frame)


if __name__ == "__main__":
    unittest.main()
