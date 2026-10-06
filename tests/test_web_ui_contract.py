import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
WEB = ROOT / "src" / "sparkle_gen2" / "web"


def test_redesigned_shell_preserves_runtime_hooks():
    html = (WEB / "index.html").read_text()
    css = (WEB / "ui" / "app.css").read_text()
    js = (WEB / "app.js").read_text()
    ui_js = (WEB / "ui" / "app.js").read_text()
    modules = {p.name: p.read_text() for p in (WEB / "ui" / "modules").glob("*.js")}
    all_js = '\n'.join(modules.values())
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
    assert "/app.css?v=23" in html
    assert "/app.js?v=23" in html
    assert "sparkle-shell-v23" in (WEB / "service-worker.js").read_text()
    assert ".command-stage" in css and ".mobile-nav" in css
    assert ".chat-structured" in css and ".chat-section" in css
    assert 'function renderMarkdown' in modules['core.js'] and 'function renderChatStructure' in modules['conversation.js']
    assert 'renderChatStructure(m.text):renderPlainText(m.text)' in modules['conversation.js']
    assert 'function renderHome' in modules['os.js'] and 'function sendImage' in modules['conversation.js']
    assert 'messages:[]' in modules['core.js'] and 'function renderMessages' in modules['conversation.js']
    assert "const userMessage={message_id:localId" in all_js
    assert "This thread is independent from your previous conversations." in all_js
    assert "Conversation workspace" in html
    assert "conversation-model" in html
    assert "function startNewConversation" in all_js
    assert "function retryMessage" in all_js
    assert "function editMessage" in all_js
    assert "data-message-edit" in all_js
    assert "data-message-retry" in all_js
    assert "/api/conversation/models" in all_js
    assert "if(b.dataset.view==='chat')startNewConversation()" not in all_js
    assert "function renderConversationContext" in all_js
    assert "conversation-inspector" in html
    assert "/context" in all_js
    assert "status:'SENDING'" in all_js
    assert "setView('chat',{load:false})" in all_js
    assert "status:'FAILED'" in all_js
    assert 'id="live-voice-panel"' in html
    assert "SPARKLE Live" in html
    assert "async function startLiveVoice" in all_js and "async function stopLiveVoice" in all_js
    assert "LIVE_RMS_FLOOR" in all_js and "LIVE_RMS_MULTIPLIER" in all_js and "LIVE_SILENCE_MS" in all_js


def test_protected_archive_is_not_referenced_by_ui():
    for path in (WEB / "index.html", WEB / "app.css", WEB / "app.js"):
        assert "source_code.zip" not in path.read_text()


def test_personal_os_domains_are_present():
    root=Path('src/sparkle_gen2/web');html=(root/'index.html').read_text();js=(root/'app.js').read_text();ui_js=(root/'ui'/'app.js').read_text();modules={p.name:p.read_text() for p in (root/'ui'/'modules').glob('*.js')}
    for name in ('goals','projects','learning','skills','research','progress','settings'):
        assert f'id=\"view-{name}\"' in html
    assert '/ui/app.js' in js and 'modules/' in ui_js
    assert '/api/os' in modules['os.js'] and 'function loadOS()' in modules['os.js']
    assert 'mobile-more-sheet' in html
    assert 'view-device-agent' in html and 'device-agent-form' in html and 'device-agent-target' in html and 'device-agent-command' in html
    assert '/api/device-agent/targets' in modules['os.js'] and 'target_device_id' in modules['os.js']
