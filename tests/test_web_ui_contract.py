import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
WEB = ROOT / "src" / "sparkle_gen2" / "web"


def test_redesigned_shell_preserves_runtime_hooks():
    html = (WEB / "index.html").read_text()
    css = (WEB / "app.css").read_text()
    js = (WEB / "app.js").read_text()
    required = [
        "pair-screen", "pair-form", "app", "nav", "mobile-nav",
        "view-home", "view-chat", "view-tasks", "view-approvals",
        "view-devices", "view-artifacts", "view-notifications",
        "hero-form", "chat-form", "image-upload", "voice-button",
        "session-picker", "task-list", "approval-list", "device-list",
        "artifact-list", "notification-list", "view-device-agent", "device-agent-form", "device-agent-target", "device-agent-command", "device-agent-result",
    ]
    for element_id in required:
        assert f'id="{element_id}"' in html
    assert "/app.css?v=11" in html
    assert "/app.js?v=18" in html
    assert "sparkle-shell-v19" in (WEB / "service-worker.js").read_text()
    assert ".command-stage" in css and ".mobile-nav" in css
    assert ".chat-structured" in css and ".chat-section" in css
    assert "function renderMarkdown" in js and "function renderChatStructure" in js
    assert "renderChatStructure(m.text):renderPlainText(m.text)" in js
    assert "function renderHome" in js and "function sendImage" in js
    assert "state.messages=[]" in js and "function renderMessages" in js
    assert "const userMessage={message_id:localId" in js
    assert "This thread is independent from your previous conversations." in js
    assert "Conversation workspace" in html
    assert "conversation-model" in html
    assert "function startNewConversation" in js
    assert "function retryMessage" in js
    assert "function editMessage" in js
    assert "data-message-edit" in js
    assert "data-message-retry" in js
    assert "/api/conversation/models" in js
    assert "if(b.dataset.view==='chat')startNewConversation()" not in js
    assert "function renderConversationContext" in js
    assert "conversation-inspector" in html
    assert "/context" in js
    assert "status:'SENDING'" in js
    assert "setView('chat',{load:false})" in js
    assert "status:'FAILED'" in js
    assert 'id="live-voice-panel"' in html
    assert "SPARKLE Live" in html
    assert "async function startLiveVoice" in js and "async function stopLiveVoice" in js
    assert "LIVE_RMS_FLOOR" in js and "LIVE_RMS_MULTIPLIER" in js and "LIVE_SILENCE_MS" in js


def test_protected_archive_is_not_referenced_by_ui():
    for path in (WEB / "index.html", WEB / "app.css", WEB / "app.js"):
        assert "source_code.zip" not in path.read_text()


def test_personal_os_domains_are_present():
    root=Path('src/sparkle_gen2/web');html=(root/'index.html').read_text();js=(root/'app.js').read_text()
    for name in ('goals','projects','learning','skills','research','progress','settings'):
        assert f'id=\"view-{name}\"' in html
    assert '/api/os' in js and 'function loadOS()' in js
    assert 'mobile-more-sheet' in html
    assert 'view-device-agent' in html and 'device-agent-form' in html and 'device-agent-target' in html and 'device-agent-command' in html
    assert '/api/device-agent/targets' in js and 'target_device_id' in js
