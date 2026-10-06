function renderPlainText(source){
  let value=String(source??'').replace(/\r\n?/g,'\n').trim();
  if(!value)return '';
  value=value.replace(/```/g,'').replace(/\*+/g,'').replace(/`+/g,'').replace(/[{}]/g,'').replace(/^\s{0,3}#{1,6}\s+/gm,'').replace(/^\s{0,3}>\s?/gm,'').replace(/^\s*[-+]\s+/gm,'');
  return esc(value).replace(/\n/g,'<br>');
}
function renderChatStructure(source){let value=String(source??'').replace(/\r\n?/g,'\n').trim();if(!value)return '';value=value.replace(/```/g,'').replace(/\*+/g,'').replace(/`+/g,'').replace(/[{}]/g,'');const lines=value.split('\n');const sections=[];let current=null;for(const raw of lines){const line=raw.trim();if(!line)continue;const numbered=line.match(/^(\d+)[.)]\s+(.*)$/);const labeled=line.match(/^([A-Za-z][A-Za-z0-9 \/&-]{2,42}):\s*(.*)$/);if(numbered||labeled){current={title:numbered?numbered[1]+'. '+numbered[2]:labeled[1],body:numbered?'':labeled[2]};sections.push(current);continue}if(current)current.body+=(current.body?' ':'')+line;else sections.push({title:'',body:line})}if(sections.length<2)return renderPlainText(value);return '<div class="chat-structured">'+sections.map((section,index)=>'<section class="chat-section"><div class="chat-section-title">'+esc(section.title||('Part '+(index+1)))+'</div><div class="chat-section-body">'+renderPlainText(section.body)+'</div></section>').join('')+'</div>'}function renderConversationContext(context){const c=context||{};$('#chat-thread-focus').textContent=c.thread_focus||'New conversation';$('#chat-intent').textContent=String(c.intent||'conversation').replace(/_/g,' ');$('#chat-continuity').textContent=c.continuity==='CONTINUOUS'?String(c.turn_count||0)+' turns · context retained':'New thread · context starts here';$('#inspector-focus').textContent=c.thread_focus||'Start a conversation to establish context.';$('#inspector-intent').textContent=String(c.intent||'conversation').replace(/_/g,' ');const related=Array.isArray(c.related_work)?c.related_work:[];$('#inspector-related').innerHTML=related.length?related.map(x=>'<div class="inspector-item"><strong>'+esc(x.title||'Related record')+'</strong><small>'+esc(x.type||'record')+' · '+esc(x.status||'ACTIVE')+'</small></div>').join(''):'<p class="muted">No directly related Personal OS work.</p>';const recent=Array.isArray(c.recent_turns)?c.recent_turns.slice(-5):[];$('#inspector-recent').innerHTML=recent.length?recent.map(x=>'<div class="inspector-item"><strong>'+esc(String(x.text||'').slice(0,180))+'</strong><small>'+esc(x.role||'turn')+'</small></div>').join(''):'<p class="muted">Your recent turns will appear here.</p>';}
function messageContext(m){return m?.metadata?.conversation_context||null}
function renderMessageActions(m){if(m.role!=='assistant')return '';return '<div class="message-actions"><button class="message-action" data-message-action="task">Create task</button><button class="message-action" data-message-action="goal">Create goal</button><button class="message-action" data-message-action="plan">Plan with SPARKLE</button></div>'}
function renderMessages(){const box=$('#messages');if(!state.session&&!state.messages.length){box.innerHTML='<div class="message assistant welcome-message"><div class="welcome-kicker">NEW THREAD</div><strong>Start a focused conversation with SPARKLE.</strong><p class="muted">This thread is independent from your previous conversations. SPARKLE will keep this thread coherent, show relevant Personal OS context, and avoid silently turning conversation into tasks.</p></div>';renderConversationContext({thread_focus:'New conversation',intent:'conversation',continuity:'NEW',turn_count:0,related_work:[],recent_turns:[]});return}box.innerHTML=state.messages.length?state.messages.map(m=>{const c=messageContext(m);const relation=m.role==='assistant'&&c?'<div class="message-relation"><span class="relation-dot"></span><span>'+esc(String(c.intent||'conversation').replace(/_/g,' '))+' · '+esc(c.continuity==='CONTINUOUS'?'context retained':'new context')+'</span></div>':'';return '<div class="message '+m.role+'" data-message-id="'+esc(m.message_id||'')+'">'+relation+(m.role==='assistant'?renderChatStructure(m.text):renderPlainText(m.text))+(m.role==='user'&&m.message_id&&!String(m.message_id).startsWith('local-')?'<div class="user-message-actions"><button data-message-edit="'+esc(m.message_id)+'">Edit</button><button data-message-retry="'+esc(m.message_id)+'">Try again</button></div>':'')+(m.role==='assistant'?renderMessageActions(m):'')+'<div class="message-meta">'+esc(timeText(m.created_at))+(m.status?' · '+esc(m.status):'')+'</div></div>'}).join(''):miniEmpty('No messages yet.');const last=[...state.messages].reverse().find(m=>m.role==='assistant'&&messageContext(m))||[...state.messages].reverse().find(m=>messageContext(m));renderConversationContext(messageContext(last)||{thread_focus:state.messages.find(m=>m.role==='user')?.text||'Conversation',intent:'conversation',continuity:state.messages.length>1?'CONTINUOUS':'NEW',turn_count:state.messages.length,related_work:[],recent_turns:[]});box.scrollTop=box.scrollHeight}
async function loadMessages(){const seq=++state.messageLoadSeq;renderMessages();if(!state.session)return;try{const [d,c]=await Promise.all([api(`/api/sessions/${encodeURIComponent(state.session)}/messages`),api(`/api/sessions/${encodeURIComponent(state.session)}/context`)]);if(seq!==state.messageLoadSeq)return;state.messages=Array.isArray(d.messages)?d.messages:[];renderMessages();renderConversationContext(c.context||null)}catch(e){if(seq===state.messageLoadSeq)toast(e.message)}}
async function send(text){
  const clean=text.trim();if(!clean)return;
  const previousSession=state.session;
  const localId=`local-${Date.now()}-${Math.random().toString(36).slice(2,7)}`;
  const userMessage={message_id:localId,session_id:previousSession||'pending',role:'user',text:clean,created_at:new Date().toISOString(),status:'SENDING'};
  state.messages=[...state.messages,userMessage];
  setView('chat',{load:false});
  renderMessages();
  $('#activity').classList.remove('hidden');
  $('#activity-text').textContent='Understanding request · checking context…';
  try{
    const d=await api('/api/chat',{method:'POST',body:JSON.stringify({text:clean,session_id:previousSession||null,model_id:$('#conversation-model')?.value||'auto',agent_id:$('#conversation-agent')?.value||'personal'})});
    state.session=d.session_id;
    localStorage.setItem('sparkle_session',state.session);
    const assistantMessage=d.message||{message_id:`assistant-${Date.now()}`,session_id:state.session,role:'assistant',text:d.result?.text||'',created_at:new Date().toISOString(),status:d.result?.status};
    const sentIndex=state.messages.findIndex(m=>m.message_id===localId);
    if(sentIndex>=0)state.messages[sentIndex]={...state.messages[sentIndex],session_id:state.session,status:'SENT'};
    else state.messages.push({...userMessage,session_id:state.session,status:'SENT'});
    state.messages=[...state.messages,assistantMessage];
    renderMessages();
    renderConversationContext(d.result?.conversation_context||messageContext(assistantMessage));
    // The response is already authoritative for this turn. Normal conversation
    // needs no immediate OS refresh; operational records refresh only when created.
    if(d.result?.goal_id)refresh().catch(()=>{});
  }catch(error){
    state.messages=state.messages.map(m=>m.message_id===localId?{...m,status:'FAILED'}:m);
    renderMessages();
    toast(error.message);
    throw error;
  }finally{
    $('#activity').classList.add('hidden');
  }
}
function bytesToBase64(bytes){let out='';const step=0x8000;for(let i=0;i<bytes.length;i+=step)out+=String.fromCharCode(...bytes.subarray(i,Math.min(i+step,bytes.length)));return btoa(out)}
async function sendImage(file,prompt=''){const allowed=new Set(['image/png','image/jpeg','image/webp']);if(!allowed.has(file.type))throw new Error('Only PNG, JPEG, or WebP images are supported');if(file.size<=0||file.size>4000000)throw new Error('Image must be 4 MB or smaller');$('#activity').classList.remove('hidden');$('#activity-text').textContent='Analyzing image with bounded multimodal routing…';try{const raw=new Uint8Array(await file.arrayBuffer());const d=await api('/api/multimodal',{method:'POST',body:JSON.stringify({modality:'image',mime_type:file.type,data_base64:bytesToBase64(raw),prompt:String(prompt||'').slice(0,2000),session_id:state.session||null})});state.session=d.session_id;localStorage.setItem('sparkle_session',state.session);await refresh();setView('chat');await loadMessages();toast('Image analyzed without storing the raw upload')}finally{$('#activity').classList.add('hidden')}}
