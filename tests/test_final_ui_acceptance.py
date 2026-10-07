import subprocess
from pathlib import Path

WEB = Path(__file__).parents[1] / 'src/sparkle_gen2/web'

def test_ui_retry_controls_and_current_view_refresh_are_wired():
    modules = {p.name:p.read_text() for p in (WEB/'ui/modules').glob('*.js')}
    assert 'function uiLoadState(' in modules['core.js']
    assert 'data-ui-retry' in modules['core.js']
    assert 'refreshCurrentView().catch' in modules['interactions.js']
    assert "reload.dataset.uiRetry==='os'" in modules['interactions.js']
    assert "reload.dataset.uiRetry==='chat'" in modules['interactions.js']
    assert "reload.dataset.uiRetry==='core'" in modules['interactions.js']
    assert "await loadWorkspacePage(reload.dataset.uiRetry)" in modules['interactions.js']
    assert 'Unable to load saved Personal OS:' in modules['os.js']
    assert 'Unable to load saved tasks:' in modules['os.js']
    assert 'Unable to load saved approvals:' in modules['os.js']
    assert 'Unable to load saved conversation:' in modules['conversation.js']

def test_ui_load_state_escapes_untrusted_error_text_and_retry_attribute():
    source=(WEB/'ui/modules/core.js').read_text()
    helpers='\n'.join(line for line in source.splitlines() if line.startswith('const esc=') or line.startswith('function uiLoadState('))
    script=helpers+"\nconst result=uiLoadState('<img src=x onerror=alert(1)>', '\" onclick=alert(1)');if(result.includes('<img')||result.includes('data-ui-retry=\"\" onclick'))process.exit(1);if(!result.includes('&lt;img')||!result.includes('&quot;'))process.exit(2);"
    subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)

def test_navigation_after_save_is_preserved_during_slow_refresh():
    source=(WEB/'ui/modules/os-editor.js').read_text()
    script='''
const modal={dataset:{kind:'research'},classList:{add(){}},setAttribute(){}};
const error={textContent:''};
const $=selector=>selector==='#os-editor'?modal:selector==='#os-editor-error'?error:{addEventListener(){}};
let view='research',calls=0,finishRefresh,startedRefresh;
const refreshing=new Promise(resolve=>finishRefresh=resolve);
const started=new Promise(resolve=>startedRefresh=resolve);
const setView=name=>view=name;
const api=async()=>{calls++;return {}};
const refresh=()=>{startedRefresh();return refreshing};
const loadOS=async()=>{};
const toast=()=>{};
globalThis.FormData=class {get(name){return name==='title'?'Synthetic research':''}};
'''+source+'''
(async()=>{
 const saving=osEditorSubmit({preventDefault(){},currentTarget:{}});
 await started;
 setView('projects');
 finishRefresh();
 await saving;
 if(view!=='projects'||calls!==1||error.textContent)process.exit(1);
})().catch(()=>process.exit(2));
'''
    subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)
