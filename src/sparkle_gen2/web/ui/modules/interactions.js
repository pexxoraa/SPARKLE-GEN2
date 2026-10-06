function startNewConversation(){state.messageLoadSeq++;state.session='';state.messages=[];localStorage.removeItem('sparkle_session');renderSessions();renderMessages()}
$$('#nav,#mobile-nav').forEach(nav=>nav.addEventListener('click',e=>{const b=e.target.closest('[data-view]');if(!b)return;setView(b.dataset.view)}));$$('[data-jump]').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.jump)));$('#menu-button').addEventListener('click',()=>$('.sidebar').classList.toggle('open'));$('#refresh').addEventListener('click',refresh);$('#conversation-agent').addEventListener('change',e=>setConversationAgent(e.target.value).catch(x=>toast(x.message)));$('#conversation-model').addEventListener('change',e=>setConversationModel(e.target.value).catch(x=>toast(x.message)));loadConversationAgents().catch(()=>{});loadConversationModels().catch(()=>{});
$('#hero-form').addEventListener('submit',async e=>{e.preventDefault();const input=$('#hero-input'),text=input.value.trim();if(!text)return;input.value='';await send(text).catch(x=>toast(x.message))});$('#chat-form').addEventListener('submit',async e=>{e.preventDefault();const input=$('#chat-input'),text=input.value.trim();if(!text)return;input.value='';await send(text).catch(x=>toast(x.message))});
$('#image-upload-button').addEventListener('click',()=>$('#image-upload').click());$('#image-upload').addEventListener('change',async e=>{const file=e.target.files?.[0];if(!file)return;const prompt=$('#chat-input').value.trim();$('#chat-input').value='';try{await sendImage(file,prompt)}catch(err){toast(err.message)}finally{e.target.value=''}});
$('#voice-button').addEventListener('click',()=>toggleVoice().catch(error=>toast(error.message)));$('#device-agent-form').addEventListener('submit',e=>{e.preventDefault();runDeviceAgent().catch(error=>toast(error.message))});document.querySelectorAll('[data-device-example]').forEach(b=>b.addEventListener('click',()=>{$('#device-agent-command').value=b.dataset.deviceExample;$('#device-agent-command').focus()}));$('#mobile-more').addEventListener('click',()=>$('#mobile-more-sheet').classList.remove('hidden'));$('#mobile-more-close').addEventListener('click',()=>$('#mobile-more-sheet').classList.add('hidden'));$('#mobile-more-sheet').addEventListener('click',e=>{const b=e.target.closest('[data-view]');if(!b)return;$('#mobile-more-sheet').classList.add('hidden');setView(b.dataset.view)});$('#live-voice-close').addEventListener('click',()=>stopLiveVoice().catch(error=>toast(error.message)));$('#live-voice-end').addEventListener('click',()=>stopLiveVoice().catch(error=>toast(error.message)));updateVoiceButton();
$('#session-picker').addEventListener('change',e=>{state.messageLoadSeq++;state.session=e.target.value;state.messages=[];if(state.session)localStorage.setItem('sparkle_session',state.session);else localStorage.removeItem('sparkle_session');renderSessions();renderMessages();loadMessages()});
$('#delete-session').addEventListener('click',()=>deleteCurrentConversation().catch(error=>toast(error.message)));$('#new-session').addEventListener('click',()=>{state.messageLoadSeq++;state.session='';state.messages=[];localStorage.removeItem('sparkle_session');renderSessions();renderMessages();setView('chat');$('#chat-input').focus();toast('New conversation ready')});
$$('[data-os-add]').forEach(b=>b.addEventListener('click',()=>osEditorOpen(b.dataset.osAdd)));
$('#os-editor-form').addEventListener('submit',osEditorSubmit);
$$('[data-os-close]').forEach(b=>b.addEventListener('click',osEditorClose));
document.addEventListener('keydown',e=>{if(e.key==='Escape')osEditorClose()});
document.addEventListener('click',async e=>{
  const edit=e.target.closest('[data-message-edit]');
  if(edit){const msg=state.messages.find(m=>m.message_id===edit.dataset.messageEdit);if(msg)editMessage(msg.message_id,msg.text);return}
  const retry=e.target.closest('[data-message-retry]');
  if(retry){await retryMessage(retry.dataset.messageRetry);return}
  const plan=e.target.closest('[data-os-plan]');
  if(plan){e.preventDefault();await planOSItem(plan.dataset.osPlan,plan.dataset.osId);return}
  const del=e.target.closest('[data-os-record-delete]');
  if(del){e.preventDefault();if(!confirm('Delete this record permanently?'))return;try{await api('/api/os/records/'+encodeURIComponent(del.dataset.osRecordDelete)+'/delete',{method:'POST',body:'{}'});await loadOS();toast('Record deleted')}catch(x){toast(x.message)}}
});
document.addEventListener('click',async e=>{
  const action=e.target.closest('[data-message-action]');
  if(action){
    const latest=[...state.messages].reverse().find(m=>m.role==='user'&&m.status!=='SENDING');
    if(!latest){toast('There is no user request to turn into work.');return}
    try{
      if(action.dataset.messageAction==='task'){
        await api('/api/os/tasks',{method:'POST',body:JSON.stringify({title:latest.text})});
        toast('Explicitly created as a task.');
        await refresh();
        setView('tasks',{load:false});
      }else if(action.dataset.messageAction==='goal'){
        await api('/api/os/goals',{method:'POST',body:JSON.stringify({title:latest.text,description:'Created explicitly from Conversation.'})});
        toast('Explicitly created as a goal.');
        await refresh();
        setView('goals',{load:false});
        await loadOS();
      }else if(action.dataset.messageAction==='plan'){
        const c=messageContext([...state.messages].reverse().find(m=>m.role==='assistant'));
        const related=(c?.related_work||[]).find(x=>x.id);
        if(!related){toast('No related Personal OS item to plan yet. Create or link one first.');return}
        await planOSItem(related.type,related.id);
      }
    }catch(x){toast(x.message)}
    return;
  }
  const inspectorAction=e.target.closest('[data-chat-action]');
  if(inspectorAction){
    const target=inspectorAction.dataset.chatAction;
    if(target==='task'){const latest=[...state.messages].reverse().find(m=>m.role==='user');if(latest){await api('/api/os/tasks',{method:'POST',body:JSON.stringify({title:latest.text})});toast('Explicitly created as a task.');await refresh();setView('tasks',{load:false})}}
    else if(target==='goal'){const latest=[...state.messages].reverse().find(m=>m.role==='user');if(latest){await api('/api/os/goals',{method:'POST',body:JSON.stringify({title:latest.text,description:'Created explicitly from Conversation.'})});toast('Explicitly created as a goal.');await refresh();setView('goals',{load:false});await loadOS()}}
    else if(target==='project')setView('projects');
    else if(target==='learning')setView('learning');
    else if(target==='research')setView('research');
  }
});
$('#task-list').addEventListener('click',async e=>{const bg=e.target.closest('[data-background]'),b=e.target.closest('[data-task]');try{if(bg){await api('/api/background',{method:'POST',body:JSON.stringify({goal_id:bg.dataset.background})});toast('Task queued for background execution');await refresh();return}if(!b)return;if(b.dataset.task==='delete'&&!confirm('Delete this task permanently?'))return;await api(`/api/tasks/${b.dataset.id}/${b.dataset.task}`,{method:'POST',body:'{}'});toast(b.dataset.task==='delete'?'Task deleted':`Task ${b.dataset.task} requested`);await refresh()}catch(x){toast(x.message)}});
$('#os-list').addEventListener('click',async e=>{const b=e.target.closest('[data-goal-delete]');if(!b)return;if(!confirm('Delete this goal permanently?'))return;try{await api(`/api/goals/${b.dataset.goalDelete}/delete`,{method:'POST',body:'{}'});await loadOS();toast('Goal deleted')}catch(x){toast(x.message)}});$('#home-approvals').addEventListener('click',async e=>{const b=e.target.closest('[data-ops-approval]');if(!b)return;try{await decideApprovalFromUi(`/api/operations/approvals/${b.dataset.id}/${b.dataset.opsApproval}`,`Approval ${b.dataset.opsApproval}d and authoritative state reread`)}catch(x){toast(x.message)}});$('#approval-list').addEventListener('click',async e=>{const b=e.target.closest('[data-approval]');if(!b)return;try{await decideApprovalFromUi(`/api/approvals/${b.dataset.id}/${b.dataset.approval}`,`Approval ${b.dataset.approval}d`)}catch(x){toast(x.message)}});$('#notification-list').addEventListener('click',async e=>{const b=e.target.closest('[data-note-read]');if(!b)return;try{await api(`/api/notifications/${b.dataset.noteRead}/read`,{method:'POST',body:'{}'});await refresh()}catch(x){toast(x.message)}});$('#device-list').addEventListener('click',async e=>{const revoke=e.target.closest('[data-device-revoke]'),rename=e.target.closest('[data-device-rename]');try{if(revoke){if(confirm('Revoke this device and invalidate its credentials?'))await api(`/api/devices/${revoke.dataset.deviceRevoke}/revoke`,{method:'POST',body:'{}'})}if(rename){const name=prompt('Device name');if(name)await api(`/api/devices/${rename.dataset.deviceRename}/rename`,{method:'POST',body:JSON.stringify({name})})}await refresh()}catch(x){toast(x.message)}});
$$('[data-task-filter]').forEach(b=>b.addEventListener('click',()=>{$$('[data-task-filter]').forEach(x=>x.classList.remove('active'));b.classList.add('active');state.filter=b.dataset.taskFilter;renderTasks()}));
$('#autonomy-mode').addEventListener('change',async e=>{try{await api('/api/settings/autonomy',{method:'POST',body:JSON.stringify({mode:e.target.value})});toast('Autonomy setting updated');await refresh()}catch(x){toast(x.message)}});
$('#enable-desktop-notifications').addEventListener('click',async()=>{try{if(!('Notification' in window)||!('serviceWorker' in navigator)){toast('Desktop notifications are unavailable in this browser');await reportDesktopCapability();return}const permission=await Notification.requestPermission();await reportDesktopCapability();if(permission==='granted'){toast('Desktop notifications enabled');await syncDesktopDeliveries()}else toast(`Desktop notifications ${permission}`)}catch(e){toast(e.message)}});
$('#forget-device').addEventListener('click',async()=>{if(confirm('Disconnect this browser from SPARKLE?')){try{await api('/api/logout',{method:'POST',body:'{}'})}catch{}localStorage.removeItem('sparkle_session');showPair()}});
function autosize(e){e.target.style.height='auto';e.target.style.height=Math.min(e.target.scrollHeight,150)+'px'};['#hero-input','#chat-input'].forEach(s=>$(s).addEventListener('input',autosize));
const h=new Date().getHours();$('#greeting').textContent=h<12?'GOOD MORNING':h<18?'GOOD AFTERNOON':'GOOD EVENING';
if('serviceWorker' in navigator)navigator.serviceWorker.register('/service-worker.js').catch(()=>{});
