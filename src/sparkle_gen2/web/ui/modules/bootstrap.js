async function syncEvents(){if($('#app').classList.contains('hidden')||document.hidden)return;try{const d=await api(`/api/events?after=${state.eventCursor}&limit=100`);if(d.cursor)state.eventCursor=d.cursor;if(d.events?.length)await refresh()}catch{}}
(async()=>{showApp();try{await refresh();const e=await api('/api/events?limit=1');state.eventCursor=e.cursor||0}catch{showPair()}setInterval(syncEvents,5000);setInterval(()=>!$('#app').classList.contains('hidden')&&!document.hidden&&refresh(),60000)})();

async function loadConversationAgents(){
  const data=await api('/api/conversation/agents');
  state.conversationAgents=data;
  const select=$('#conversation-agent');if(!select)return;
  select.innerHTML=(data.agents||[]).map(x=>'<option value="'+esc(x.agent_id)+'">'+esc(x.name)+'</option>').join('');
  select.value=data.selected||'personal';
}
async function setConversationAgent(agentId){
  const data=await api('/api/conversation/agent',{method:'POST',body:JSON.stringify({agent_id:agentId||'personal'})});
  state.conversationAgents=data;
  toast('Agent selected: '+(data.selected?.name||agentId));
}

async function loadConversationModels(){
  try{
    const data=await api('/api/conversation/models');
    state.conversationModels=data;
    const select=$('#conversation-model');if(!select)return;
    const rows=data.models||[];
    select.innerHTML='<option value="auto">Auto · fastest suitable</option>'+rows.filter(x=>x.configured&&x.enabled&&x.health!=='UNAVAILABLE').map(x=>'<option value="'+esc(x.record_id)+'">'+esc(x.provider)+' · '+esc(x.model_id)+' · '+esc(x.latency_class)+'</option>').join('');
    select.value=data.selected||'auto';
  }catch(error){console.warn('conversation model inventory unavailable',error)}
}
async function setConversationModel(modelId){
  const data=await api('/api/conversation/model',{method:'POST',body:JSON.stringify({model_id:modelId||'auto'})});
  state.conversationModels=data;
  toast(modelId==='auto'?'Agent set to Auto.':'Agent selected for new replies.');
}
async function retryMessage(messageId){
  if(!state.session)return;
  $('#activity').classList.remove('hidden');$('#activity-text').textContent='Trying again…';
  try{
    const d=await api('/api/conversation/retry',{method:'POST',body:JSON.stringify({session_id:state.session,message_id:messageId,model_id:$('#conversation-model')?.value||'auto',agent_id:$('#conversation-agent')?.value||'personal'})});
    state.session=d.session_id;localStorage.setItem('sparkle_session',state.session);await loadMessages();toast('New response generated.');
  }catch(error){toast(error.message)}finally{$('#activity').classList.add('hidden')}
}
async function editMessage(messageId,current){
  const node=document.querySelector('[data-message-id="'+CSS.escape(messageId)+'"]');if(!node)return;
  const editor=document.createElement('div');editor.className='message-editor';editor.innerHTML='<textarea></textarea><div class="message-editor-actions"><button type="button" class="message-action" data-edit-cancel>Cancel</button><button type="button" class="message-action" data-edit-send>Send & replace</button></div>';
  editor.querySelector('textarea').value=current;node.appendChild(editor);editor.querySelector('textarea').focus();
  editor.querySelector('[data-edit-cancel]').onclick=()=>editor.remove();
  editor.querySelector('[data-edit-send]').onclick=async()=>{const value=editor.querySelector('textarea').value.trim();if(!value)return;$('#activity').classList.remove('hidden');$('#activity-text').textContent='Editing and regenerating…';try{const d=await api('/api/conversation/edit',{method:'POST',body:JSON.stringify({session_id:state.session,message_id:messageId,text:value,model_id:$('#conversation-model')?.value||'auto',agent_id:$('#conversation-agent')?.value||'personal'})});state.session=d.session_id;localStorage.setItem('sparkle_session',state.session);await loadMessages();toast('Message edited and regenerated.')}catch(error){toast(error.message)}finally{$('#activity').classList.add('hidden')}};
}
