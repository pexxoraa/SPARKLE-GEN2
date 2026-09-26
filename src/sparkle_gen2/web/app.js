const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const state={device:null,data:null,operations:null,session:localStorage.getItem('sparkle_session')||'',filter:'all',eventCursor:0,desktopPermission:'unknown',refreshing:null,lastDesktopSyncAt:0};
const voice={recording:false,busy:false,waiting:false,sessionId:'',stream:null,context:null,source:null,processor:null,sink:null,buffers:[],samples:0,sampleRate:0,limitTriggered:false};
const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
function toast(message){const el=$('#toast');el.textContent=message;el.classList.remove('hidden');clearTimeout(el._t);el._t=setTimeout(()=>el.classList.add('hidden'),2800)}
async function api(path,opts={}){const headers={'Content-Type':'application/json',...(opts.headers||{})};const r=await fetch(path,{...opts,headers,credentials:'same-origin'});let data={};try{data=await r.json()}catch{}if(!r.ok)throw new Error(data.error||`Request failed (${r.status})`);return data}
function showPair(){document.body.classList.remove('ready');$('#pair-screen').classList.remove('hidden');$('#app').classList.add('hidden');$('#pair-os').value=navigator.platform||'Browser';}
function showApp(){document.body.classList.add('ready');$('#pair-screen').classList.add('hidden');$('#app').classList.remove('hidden');}
function statusClass(status){return ['COMPLETED','ONLINE','ACTIVE','CONNECTED','HEALTHY','LIVE_VERIFIED','LIVE_ACCEPTED'].includes(status)?'status':'status waiting'}
function timeText(value){if(!value)return '—';try{return new Intl.DateTimeFormat([], {dateStyle:'medium',timeStyle:'short'}).format(new Date(value))}catch{return value}}
function setView(name){$$('.view').forEach(v=>v.classList.toggle('active',v.id===`view-${name}`));$$('.nav-item').forEach(v=>v.classList.toggle('active',v.dataset.view===name));const titles={home:['PERSONAL WORKSPACE','Home'],chat:['CONTINUOUS CONTEXT','Conversation'],tasks:['ORCHESTRATION','Tasks'],approvals:['HUMAN AUTHORITY','Approvals'],devices:['TRUST BOUNDARY','Devices'],notifications:['ATTENTION','Notifications'],artifacts:['VERIFIED OUTPUTS','Artifacts']};$('#view-eyebrow').textContent=titles[name][0];$('#view-title').textContent=titles[name][1];$('.sidebar').classList.remove('open');if(name==='chat')loadMessages();}
function miniEmpty(text){return `<p class="muted">${esc(text)}</p>`}
function renderTaskCard(t){return `<article class="task-card"><div class="row"><div><div class="status">${esc(t.status)}</div><h3>${esc(t.goal||'Background task')}</h3></div><strong>${Number(t.progress)||0}%</strong></div><p class="muted">${esc(t.current_operation?`Current: ${t.current_operation}`:'No active operation')}</p><div class="progress"><span style="width:${Math.max(0,Math.min(100,Number(t.progress)||0))}%"></span></div></article>`}
function renderHome(){
  const ops=state.operations||{},today=ops.today||{},oper=ops.operations||{},intel=ops.intelligence||{};
  const next=ops.next_action||{};$('#home-next-action').innerHTML=next.status&&next.status!=='NONE'?`<div class="mini-row"><span><b>${esc(next.title)}</b><br><small class="muted">${esc(next.source)} · ${esc(next.status)}</small></span></div>`:miniEmpty('No unresolved action.');
  const daily=today.daily_brief||{},brief=daily.brief||null;
  $('#home-daily').innerHTML=brief?`<div class="mini-row"><span><b>${esc(brief.day||daily.day)}</b><br><small class="muted">${Number(daily.unresolved_count||0)} open · ${Number(daily.completed_count||0)} done</small></span><span class="${statusClass(brief.status)}">${esc(brief.status)}</span></div>`+(brief.items||[]).slice(0,4).map(x=>`<div class="mini-row"><span>${esc(x.title)}${x.carried_forward?' <small class="muted">carried</small>':''}<br><small class="muted">${esc(x.source)} · ${esc(x.state)}</small></span><b>${Number(x.score||0).toFixed(2)}</b></div>`).join(''):miniEmpty(`No persisted Daily Brief for ${esc(daily.day||'today')}.`);
  const attention=today.attention||[];$('#home-attention').innerHTML=attention.length?attention.slice(0,6).map(x=>`<div class="mini-row"><span><b>${esc(x.title||x.kind)}</b><br><small class="muted">${esc(x.reason||'Needs attention')}</small></span><span class="status waiting">${esc(x.status)}</span></div>`).join(''):miniEmpty('No failed or blocked work needs attention.');
  const tasks=(today.active_work||[]).slice(0,3);$('#active-work').innerHTML=tasks.length?tasks.map(renderTaskCard).join(''):miniEmpty('No active tasks. Ask SPARKLE to start something.');
  const approvals=oper.pending_approvals||[];$('#home-approvals').innerHTML=approvals.length?approvals.slice(0,4).map(a=>`<div class="mini-row"><span><b>${esc(a.action)}</b><br><small class="muted">${esc(a.capability)} · ${esc(a.risk)} risk</small></span><span><button class="action approve" data-ops-approval="approve" data-id="${esc(a.approval_id)}">Approve</button> <button class="action reject" data-ops-approval="reject" data-id="${esc(a.approval_id)}">Reject</button></span></div>`).join(''):miniEmpty('Nothing is waiting for approval.');
  const devices=state.data?.devices||[];$('#home-devices').innerHTML=devices.length?devices.slice(0,4).map(d=>`<div class="mini-row"><span>${esc(d.name)}</span><span class="status">${esc(d.status)}</span></div>`).join(''):miniEmpty('No authorized clients.');
  const notes=(today.notifications||[]).slice(0,4);$('#home-notifications').innerHTML=notes.length?notes.map(n=>`<div class="mini-row"><span><b>${esc(n.title)}</b>${Number(n.occurrence_count||1)>1?` <small class="muted">×${Number(n.occurrence_count)}</small>`:''}<br><small class="muted">${esc(n.body)}</small>${n.why?`<br><small class="muted">Why: ${esc(n.why)}</small>`:''}</span><span>${esc(n.priority)}</span></div>`).join(''):miniEmpty('No recent notifications.');
  const models=(intel.capabilities?.models||[]),registry=(intel.capabilities?.registry||[]),acceptance=Object.fromEntries(registry.map(x=>[x.capability,x]));$('#home-capabilities').innerHTML=models.length?`<p class="muted">Model capabilities</p>`+models.map(x=>`<div class="mini-row"><span>${esc(x.capability==='voice'&&acceptance.voice_stt_tts?.status==='LIVE_VERIFIED'?'voice · Gemini 3.8 Live':x.capability)}</span><span class="${statusClass((x.capability==='voice'&&acceptance.voice_stt_tts?.status==='LIVE_VERIFIED')?'LIVE_ACCEPTED':x.status)}">${esc((x.capability==='voice'&&acceptance.voice_stt_tts?.status==='LIVE_VERIFIED')?'LIVE_ACCEPTED':x.status)}</span></div>`).join(''):miniEmpty('Model capability state unavailable.');
  const conns=intel.connectors||{};$('#home-connectors').innerHTML=(conns.items||[]).length?`<p class="muted">Connectors</p>`+conns.items.slice(0,6).map(x=>`<div class="mini-row"><span>${esc(x.name)}</span><span class="${x.status==='CONNECTED'?'status':'status waiting'}">${esc(x.status)}</span></div>`).join(''):`<p class="muted">Connectors: ${esc(conns.status||'UNAVAILABLE')}</p>`;
  const world=intel.world_state||{};$('#home-world').innerHTML=(world.items||[]).length?`<p class="muted">World state</p>`+world.items.slice(0,5).map(x=>`<div class="mini-row"><span>${esc(x.node_id)} · ${esc(x.kind)}</span><span class="${x.freshness==='FRESH'?'status':'status waiting'}">${esc(x.freshness)}</span></div>`).join(''):`<p class="muted">World state: ${esc(world.status||'UNAVAILABLE')}</p>`;
}
function renderTasks(){const all=state.data?.tasks||[];const filtered=all.filter(t=>state.filter==='all'||(state.filter==='active'&&!['COMPLETED','CANCELLED','FAILED','BLOCKED'].includes(t.status))||(state.filter==='waiting'&&['WAITING','BLOCKED'].includes(t.status))||(state.filter==='complete'&&t.status==='COMPLETED'));$('#task-list').innerHTML=filtered.length?filtered.map(t=>`<article class="list-card"><div class="head"><div><span class="${statusClass(t.status)}">${esc(t.status)}</span><h3>${esc(t.goal||t.goal_id)}</h3><p class="muted">Started ${esc(timeText(t.started))} · ${esc(t.current_operation||'No active step')}</p></div><strong>${Number(t.progress)||0}%</strong></div><div class="progress"><span style="width:${Math.max(0,Math.min(100,Number(t.progress)||0))}%"></span></div><div class="actions">${!['COMPLETED','CANCELLED'].includes(t.status)?`<button class="action" data-background="${esc(t.goal_id)}">Background</button><button class="action" data-task="resume" data-id="${esc(t.goal_id)}">Resume</button><button class="action" data-task="replan" data-id="${esc(t.goal_id)}">Replan</button><button class="action danger" data-task="cancel" data-id="${esc(t.goal_id)}">Cancel</button>`:''}</div></article>`).join(''):miniEmpty('No tasks in this view.');}
function renderApprovals(){const rows=state.data?.pending_approvals||[];$('#approval-list').innerHTML=rows.length?rows.map(a=>`<article class="list-card"><div class="head"><div><span class="status">${esc(a.risk)} RISK</span><h3>${esc(a.action)}</h3><p class="muted">Capability: ${esc(a.capability)} · Scope: ${esc(a.requested_scope)}<br>Requested ${esc(timeText(a.requested_at))}${a.expires_at?` · Expires ${esc(timeText(a.expires_at))}`:''}</p></div></div><div class="actions"><button class="action approve" data-approval="approve" data-id="${esc(a.approval_id)}">Approve</button><button class="action reject" data-approval="reject" data-id="${esc(a.approval_id)}">Reject</button></div></article>`).join(''):miniEmpty('No pending approvals.');}
function renderDevices(){const rows=state.data?.devices||[];$('#device-list').innerHTML=rows.length?rows.map(d=>`<article class="device-card"><div class="device-icon">${d.kind==='phone'?'▯':d.kind==='tablet'?'▭':'⌁'}</div><h3>${esc(d.name)}</h3><p><span class="${statusClass(d.status)}">${esc(d.status)}</span> · ${esc(d.kind)} · ${esc(d.os_name)}</p><p class="muted">Last seen ${esc(timeText(d.last_seen))}</p><div class="capabilities">${(d.capabilities||[]).map(c=>`<span class="cap">${esc(c)}</span>`).join('')}</div><div class="actions"><button class="action" data-device-rename="${esc(d.device_id)}">Rename</button>${state.device?.device_id!==d.device_id?`<button class="action danger" data-device-revoke="${esc(d.device_id)}">Revoke</button>`:''}</div></article>`).join(''):miniEmpty('No authorized devices.');}
function renderArtifacts(){const rows=[...(state.data?.artifacts||[])];$('#artifact-list').innerHTML=rows.length?rows.map(a=>`<article class="list-card"><div class="head"><div><span class="status">${esc(a.status)}</span><h3>${esc(a.project_name)}</h3><p class="muted">${esc(a.artifact_name)} · ${Number(a.artifact_bytes||0).toLocaleString()} bytes<br>SHA-256 ${esc(String(a.artifact_sha256||'').slice(0,16))}… · ${esc(timeText(a.created_at))}</p></div></div><div class="actions"><a class="action" href="/api/artifacts/${encodeURIComponent(a.artifact_id)}/download">Download verified package</a></div></article>`).join(''):miniEmpty('No generated artifacts yet.');}
function renderNotifications(){const rows=[...(state.data?.notifications||[])].reverse();$('#notification-list').innerHTML=rows.length?rows.map(n=>`<article class="list-card"><div class="head"><div><span class="status">${esc(n.priority)}${n.decision?` · ${esc(n.decision)}`:''}</span><h3>${esc(n.title)}${Number(n.occurrence_count||1)>1?` <small class="muted">×${Number(n.occurrence_count)}</small>`:''}</h3><p class="muted">${esc(n.body)}${n.why?`<br>Why: ${esc(n.why)}`:''}<br>${esc(timeText(n.created_at))}</p></div><span>${esc(n.status)}</span></div>${n.status==='UNREAD'?`<div class="actions"><button class="action" data-note-read="${esc(n.notification_id)}">Mark read</button></div>`:''}</article>`).join(''):miniEmpty('No notifications.');}
function renderSessions(){const picker=$('#session-picker');const rows=state.data?.sessions||[];picker.innerHTML=`<option value="">New conversation</option>`+rows.map(s=>`<option value="${esc(s.session_id)}" ${s.session_id===state.session?'selected':''}>${esc(s.active_goal_id?'Active conversation':'Conversation')} · ${esc(s.session_id.slice(0,8))}</option>`).join('');}
function renderBadges(){const a=(state.data?.pending_approvals||[]).length,n=(state.data?.notifications||[]).filter(x=>x.status==='UNREAD').length;[['#approval-badge',a],['#notification-badge',n]].forEach(([sel,v])=>{const e=$(sel);e.textContent=v;e.classList.toggle('hidden',!v)})}
async function reportDesktopCapability(){const supported=('Notification' in window)&&('serviceWorker' in navigator);const permission=supported?Notification.permission:'unknown';state.desktopPermission=permission;const el=$('#notification-channel-status');if(el)el.textContent=!supported?'Desktop notifications unavailable in this browser.':`Desktop permission: ${permission}.`;try{await api('/api/notification-channels/desktop',{method:'POST',body:JSON.stringify({supported,permission})})}catch{}return {supported,permission}}
async function syncDesktopDeliveries(){const c=await reportDesktopCapability();if(!c.supported||c.permission!=='granted')return;let pending;try{pending=(await api('/api/notification-deliveries/pending?channel=desktop')).attempts||[]}catch{return}if(!pending.length)return;const reg=await navigator.serviceWorker.ready;for(const a of pending){try{await reg.showNotification(a.payload?.title||'SPARKLE',{body:a.payload?.body||'Open SPARKLE for details.',tag:`sparkle-${a.attempt_id}`,renotify:false,data:{attempt_id:a.attempt_id,notification_id:a.notification_id}});await api(`/api/notification-deliveries/${a.attempt_id}/result`,{method:'POST',body:JSON.stringify({status:'ACCEPTED',channel_reference:`service-worker:${a.attempt_id}`})})}catch(e){try{await api(`/api/notification-deliveries/${a.attempt_id}/result`,{method:'POST',body:JSON.stringify({status:'FAILED',error:String(e?.message||'browser_notification_failed').slice(0,200)})})}catch{}}}}
async function refresh(){
  if(state.refreshing)return state.refreshing;
  state.refreshing=(async()=>{
    try{
      const [data,tasks,operations]=await Promise.all([
        api('/api/state'),
        api('/api/tasks'),
        api('/api/operations')
      ]);

      state.data={...data,tasks:tasks.tasks};
      state.operations=operations;
      state.device=(data.devices||[]).find(
        d=>d.status==='ONLINE'&&d.device_id===state.device?.device_id
      )||state.device;

      renderHome();
      renderTasks();
      renderApprovals();
      renderDevices();
      renderArtifacts();
      renderNotifications();
      renderSessions();
      renderBadges();

      if(state.data?.autonomy)
        $('#autonomy-mode').value=state.data.autonomy.mode;

      $('#core-status').textContent='Personal Core online';
      $('#device-pill').textContent=state.device?.name||'This device';

      const now=Date.now();
      if(
        now-state.lastDesktopSyncAt>60000 &&
        state.desktopPermission!=='denied'
      ){
        state.lastDesktopSyncAt=now;
        syncDesktopDeliveries().catch(()=>{});
      }
    }catch(e){
      if(/authentication|token|revoked/.test(e.message)){
        showPair();
        return;
      }
      $('#core-status').textContent='Personal Core unavailable';
      toast(e.message);
    }finally{
      state.refreshing=null;
    }
  })();
  return state.refreshing;
}
async function loadMessages(){const box=$('#messages');if(!state.session){box.innerHTML=`<div class="message assistant">Hello. I’m SPARKLE. Start here and continue this same conversation from any authorized device.</div>`;return}try{const d=await api(`/api/sessions/${state.session}/messages`);box.innerHTML=d.messages.length?d.messages.map(m=>`<div class="message ${m.role}">${esc(m.text)}<div class="message-meta">${esc(timeText(m.created_at))}${m.status?` · ${esc(m.status)}`:''}</div></div>`).join(''):miniEmpty('No messages yet.');box.scrollTop=box.scrollHeight}catch(e){toast(e.message)}}
async function send(text){
  if(!text.trim())return;
  $('#activity').classList.remove('hidden');
  $('#activity-text').textContent='Planning and checking policy…';

  try{
    const d=await api('/api/chat',{
      method:'POST',
      body:JSON.stringify({
        text,
        session_id:state.session||null
      })
    });

    state.session=d.session_id;
    localStorage.setItem('sparkle_session',state.session);

    // setView('chat') already triggers loadMessages() once.
    // Do not perform a second message fetch here.
    setView('chat');

    // Dashboard state is refreshed in the background.
    refresh().catch(()=>{});
  }finally{
    $('#activity').classList.add('hidden');
  }
}
function bytesToBase64(bytes){let out='';const step=0x8000;for(let i=0;i<bytes.length;i+=step)out+=String.fromCharCode(...bytes.subarray(i,Math.min(i+step,bytes.length)));return btoa(out)}
async function sendImage(file,prompt=''){const allowed=new Set(['image/png','image/jpeg','image/webp']);if(!allowed.has(file.type))throw new Error('Only PNG, JPEG, or WebP images are supported');if(file.size<=0||file.size>4000000)throw new Error('Image must be 4 MB or smaller');$('#activity').classList.remove('hidden');$('#activity-text').textContent='Analyzing image with bounded multimodal routing…';try{const raw=new Uint8Array(await file.arrayBuffer());const d=await api('/api/multimodal',{method:'POST',body:JSON.stringify({modality:'image',mime_type:file.type,data_base64:bytesToBase64(raw),prompt:String(prompt||'').slice(0,2000),session_id:state.session||null})});state.session=d.session_id;localStorage.setItem('sparkle_session',state.session);await refresh();setView('chat');await loadMessages();toast('Image analyzed without storing the raw upload')}finally{$('#activity').classList.add('hidden')}}

function audioContextClass(){return window.AudioContext||window.webkitAudioContext||null}
function voiceSupported(){return !!(navigator.mediaDevices?.getUserMedia&&audioContextClass())}
function updateVoiceButton(){
  const button=$('#voice-button');if(!button)return;
  const supported=voiceSupported();
  button.disabled=!supported||voice.busy||voice.waiting;
  button.classList.toggle('recording',voice.recording);
  button.textContent=voice.recording?'■':'◉';
  const label=!supported?'Voice capture is unavailable in this browser':voice.waiting?'Voice action is waiting for approval':voice.recording?'Stop and send voice message':'Record a voice message';
  button.title=label;button.setAttribute('aria-label',label);
}
function detachVoiceCapture(closeContext=true){
  const context=voice.context;
  try{if(voice.processor)voice.processor.onaudioprocess=null}catch{}
  try{voice.source?.disconnect()}catch{}
  try{voice.processor?.disconnect()}catch{}
  try{voice.sink?.disconnect()}catch{}
  try{voice.stream?.getTracks().forEach(track=>track.stop())}catch{}
  voice.stream=null;voice.source=null;voice.processor=null;voice.sink=null;voice.context=null;
  if(closeContext&&context&&context.state!=='closed')context.close().catch(()=>{});
  return context;
}
function resampleVoicePcm16(buffers,sourceRate){
  const total=buffers.reduce((n,b)=>n+b.length,0);
  if(!Number.isFinite(sourceRate)||sourceRate<=0||total<=0)throw new Error('No microphone audio was captured');
  if(total>sourceRate*30)throw new Error('Voice messages are limited to 30 seconds');
  const input=new Float32Array(total);let at=0;
  for(const part of buffers){input.set(part,at);at+=part.length}
  const count=Math.max(1,Math.floor(total*24000/sourceRate));
  const output=new Uint8Array(count*2),view=new DataView(output.buffer);
  for(let i=0;i<count;i++){
    const position=i*sourceRate/24000,left=Math.floor(position),fraction=position-left;
    const a=input[Math.min(left,input.length-1)],b=input[Math.min(left+1,input.length-1)];
    const sample=Math.max(-1,Math.min(1,a+(b-a)*fraction));
    view.setInt16(i*2,sample<0?Math.round(sample*32768):Math.round(sample*32767),true);
  }
  return output;
}
function base64ToBytes(text){const raw=atob(String(text||'')),out=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)out[i]=raw.charCodeAt(i);return out}
async function playVoiceChunks(chunks,context=null){
  const rows=[...(chunks||[])].sort((a,b)=>(Number(a.sequence)||0)-(Number(b.sequence)||0));
  if(!rows.length)return false;
  let total=0;const decoded=[];
  for(const row of rows){
    if(row.sample_rate!==24000||row.channels!==1||row.sample_width!==2||row.encoding!=='pcm_s16le'||!row.audio_base64)throw new Error('Voice response audio format is invalid');
    const bytes=base64ToBytes(row.audio_base64);if(!bytes.length||bytes.length%2)throw new Error('Voice response audio is malformed');
    total+=bytes.length;if(total>4000000)throw new Error('Voice response audio exceeds the browser playback limit');decoded.push(bytes);
  }
  const Ctx=audioContextClass();if(!Ctx)throw new Error('Audio playback is unavailable in this browser');
  const own=!context;const ctx=context||new Ctx();
  if(ctx.state==='suspended')await ctx.resume();
  const samples=total/2,buffer=ctx.createBuffer(1,samples,24000),channel=buffer.getChannelData(0);let cursor=0;
  for(const bytes of decoded){const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);for(let i=0;i<bytes.length;i+=2)channel[cursor++]=view.getInt16(i,true)/32768}
  const source=ctx.createBufferSource();source.buffer=buffer;source.connect(ctx.destination);
  await new Promise((resolve,reject)=>{source.onended=resolve;try{source.start()}catch(error){reject(error)}});
  try{source.disconnect()}catch{}if(own&&ctx.state!=='closed')await ctx.close();return true;
}
async function syncVoiceConversation(sessionId){
  const inspected=await api(`/api/voice/sessions/${encodeURIComponent(sessionId)}`);
  const conversation=inspected.session?.conversation_session_id;
  if(conversation){state.session=conversation;localStorage.setItem('sparkle_session',conversation)}
  return inspected;
}
async function closeVoiceSession(sessionId){
  if(!sessionId)return;
  try{await api(`/api/voice/sessions/${encodeURIComponent(sessionId)}/close`,{method:'POST',body:'{}'})}catch{}
}
async function handleVoicePayload(payload,context=null){
  const rows=Array.isArray(payload?.voice)?payload.voice:[];let played=false;
  for(const row of rows){
    if(row.session_id){try{await syncVoiceConversation(row.session_id)}catch{}}
    if(row.audio_chunks?.length)played=(await playVoiceChunks(row.audio_chunks,context))||played;
    if(row.session_id)await closeVoiceSession(row.session_id);
    if(row.session_id===voice.sessionId){voice.sessionId='';voice.waiting=false;updateVoiceButton()}
  }
  return played;
}
async function startVoice(){
  if(voice.busy||voice.recording||voice.waiting)return;
  if(!voiceSupported())throw new Error('Microphone capture is unavailable in this browser');
  voice.busy=true;updateVoiceButton();let opened='';
  try{
    const health=await api('/api/voice/status');
    if(health.status!=='HEALTHY'||!health.live_verified)throw new Error(health.reason||'Voice provider is not live verified');
    const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
    const Ctx=audioContextClass(),context=new Ctx();await context.resume();
    voice.stream=stream;voice.context=context;voice.sampleRate=context.sampleRate;voice.buffers=[];voice.samples=0;voice.limitTriggered=false;
    const started=await api('/api/voice/sessions',{method:'POST',body:JSON.stringify({conversation_session_id:state.session||null,classification:'PRIVATE',persist_transcript:true})});
    if(started.state!=='CONNECTED')throw new Error(started.failure_reason||'Voice session could not connect');
    opened=started.session_id;voice.sessionId=opened;
    const source=context.createMediaStreamSource(stream),processor=context.createScriptProcessor(4096,1,1),sink=context.createGain();sink.gain.value=0;
    voice.source=source;voice.processor=processor;voice.sink=sink;voice.recording=true;
    processor.onaudioprocess=event=>{
      if(!voice.recording)return;
      const input=event.inputBuffer.getChannelData(0),limit=Math.floor(voice.sampleRate*30),remaining=Math.max(0,limit-voice.samples);
      if(remaining>0){const copy=new Float32Array(input.subarray(0,Math.min(input.length,remaining)));voice.buffers.push(copy);voice.samples+=copy.length}
      if(voice.samples>=limit&&!voice.limitTriggered){voice.limitTriggered=true;setTimeout(()=>stopVoice().catch(error=>toast(error.message)),0)}
    };
    source.connect(processor);processor.connect(sink);sink.connect(context.destination);
    toast('Listening — tap the voice button again to send');
  }catch(error){
    detachVoiceCapture(true);if(opened)await closeVoiceSession(opened);voice.sessionId='';voice.recording=false;throw error;
  }finally{voice.busy=false;updateVoiceButton()}
}
async function stopVoice(){
  if(voice.busy||!voice.recording)return;
  voice.busy=true;voice.recording=false;updateVoiceButton();
  const sessionId=voice.sessionId,buffers=voice.buffers.slice(),sampleRate=voice.sampleRate,playbackContext=detachVoiceCapture(false);
  voice.buffers=[];voice.samples=0;voice.sampleRate=0;$('#activity').classList.remove('hidden');$('#activity-text').textContent='Transcribing and checking policy…';
  try{
    const pcm=resampleVoicePcm16(buffers,sampleRate);let response=null,sequence=0;
    for(let offset=0;offset<pcm.length;offset+=48000){
      const part=pcm.subarray(offset,Math.min(offset+48000,pcm.length));
      response=await api(`/api/voice/sessions/${encodeURIComponent(sessionId)}/audio`,{method:'POST',body:JSON.stringify({audio_base64:bytesToBase64(part),sequence:sequence++,final:offset+48000>=pcm.length})});
    }
    await syncVoiceConversation(sessionId);
    if(response?.agent_result?.status==='WAITING'){
      voice.waiting=true;if(playbackContext&&playbackContext.state!=='closed')await playbackContext.close();
      await refresh();setView('approvals');toast('Voice action is waiting for your approval');return;
    }
    if(!response?.audio_chunks?.length)throw new Error('Voice provider returned no authorized response audio');
    await playVoiceChunks(response.audio_chunks,playbackContext);
    if(playbackContext&&playbackContext.state!=='closed')await playbackContext.close();
    await closeVoiceSession(sessionId);voice.sessionId='';voice.waiting=false;
    await refresh();setView('chat');await loadMessages();
  }catch(error){
    if(playbackContext&&playbackContext.state!=='closed')await playbackContext.close().catch(()=>{});
    await closeVoiceSession(sessionId);voice.sessionId='';voice.waiting=false;throw error;
  }finally{$('#activity').classList.add('hidden');voice.busy=false;updateVoiceButton()}
}
async function toggleVoice(){if(voice.recording)return stopVoice();return startVoice()}
function prepareVoicePlaybackContext(){const Ctx=audioContextClass();if(!Ctx)return null;try{const context=new Ctx();context.resume().catch(()=>{});return context}catch{return null}}
async function decideApprovalFromUi(path,message){
  const playback=prepareVoicePlaybackContext();
  try{
    const result=await api(path,{method:'POST',body:'{}'});
    const played=await handleVoicePayload(result,playback);
    toast(message);
    await refresh();
    if(played){setView('chat');await loadMessages()}
  }finally{if(playback&&playback.state!=='closed')await playback.close().catch(()=>{})}
}

$('#pair-form').addEventListener('submit',async e=>{e.preventDefault();$('#pair-error').textContent='';try{const caps=['conversation','notifications','approvals','task_status','device_management','artifacts'];const d=await api('/api/enroll',{method:'POST',body:JSON.stringify({code:$('#pair-code').value.trim(),name:$('#pair-name').value.trim(),kind:$('#pair-kind').value,os:$('#pair-os').value.trim(),capabilities:caps,client:'web'})});state.device=d.device;showApp();await refresh()}catch(err){$('#pair-error').textContent=err.message}});
$('#nav').addEventListener('click',e=>{const b=e.target.closest('[data-view]');if(b)setView(b.dataset.view)});$$('[data-jump]').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.jump)));$('#menu-button').addEventListener('click',()=>$('.sidebar').classList.toggle('open'));$('#refresh').addEventListener('click',refresh);
$('#hero-form').addEventListener('submit',async e=>{e.preventDefault();const input=$('#hero-input'),text=input.value.trim();if(!text)return;input.value='';await send(text).catch(x=>toast(x.message))});$('#chat-form').addEventListener('submit',async e=>{e.preventDefault();const input=$('#chat-input'),text=input.value.trim();if(!text)return;input.value='';await send(text).catch(x=>toast(x.message))});
$('#image-upload-button').addEventListener('click',()=>$('#image-upload').click());$('#image-upload').addEventListener('change',async e=>{const file=e.target.files?.[0];if(!file)return;const prompt=$('#chat-input').value.trim();$('#chat-input').value='';try{await sendImage(file,prompt)}catch(err){toast(err.message)}finally{e.target.value=''}});
$('#voice-button').addEventListener('click',()=>toggleVoice().catch(error=>toast(error.message)));updateVoiceButton();
$('#session-picker').addEventListener('change',e=>{state.session=e.target.value;localStorage.setItem('sparkle_session',state.session);loadMessages()});$('#new-session').addEventListener('click',()=>{state.session='';localStorage.removeItem('sparkle_session');renderSessions();loadMessages()});
$('#task-list').addEventListener('click',async e=>{const bg=e.target.closest('[data-background]'),b=e.target.closest('[data-task]');try{if(bg){await api('/api/background',{method:'POST',body:JSON.stringify({goal_id:bg.dataset.background})});toast('Task queued for background execution');await refresh();return}if(!b)return;await api(`/api/tasks/${b.dataset.id}/${b.dataset.task}`,{method:'POST',body:'{}'});toast(`Task ${b.dataset.task} requested`);await refresh()}catch(x){toast(x.message)}});$('#home-approvals').addEventListener('click',async e=>{const b=e.target.closest('[data-ops-approval]');if(!b)return;try{await decideApprovalFromUi(`/api/operations/approvals/${b.dataset.id}/${b.dataset.opsApproval}`,`Approval ${b.dataset.opsApproval}d and authoritative state reread`)}catch(x){toast(x.message)}});$('#approval-list').addEventListener('click',async e=>{const b=e.target.closest('[data-approval]');if(!b)return;try{await decideApprovalFromUi(`/api/approvals/${b.dataset.id}/${b.dataset.approval}`,`Approval ${b.dataset.approval}d`)}catch(x){toast(x.message)}});$('#notification-list').addEventListener('click',async e=>{const b=e.target.closest('[data-note-read]');if(!b)return;try{await api(`/api/notifications/${b.dataset.noteRead}/read`,{method:'POST',body:'{}'});await refresh()}catch(x){toast(x.message)}});$('#device-list').addEventListener('click',async e=>{const revoke=e.target.closest('[data-device-revoke]'),rename=e.target.closest('[data-device-rename]');try{if(revoke){if(confirm('Revoke this device and invalidate its credentials?'))await api(`/api/devices/${revoke.dataset.deviceRevoke}/revoke`,{method:'POST',body:'{}'})}if(rename){const name=prompt('Device name');if(name)await api(`/api/devices/${rename.dataset.deviceRename}/rename`,{method:'POST',body:JSON.stringify({name})})}await refresh()}catch(x){toast(x.message)}});
$$('[data-task-filter]').forEach(b=>b.addEventListener('click',()=>{$$('[data-task-filter]').forEach(x=>x.classList.remove('active'));b.classList.add('active');state.filter=b.dataset.taskFilter;renderTasks()}));
$('#autonomy-mode').addEventListener('change',async e=>{try{await api('/api/settings/autonomy',{method:'POST',body:JSON.stringify({mode:e.target.value})});toast('Autonomy setting updated');await refresh()}catch(x){toast(x.message)}});
$('#enable-desktop-notifications').addEventListener('click',async()=>{try{if(!('Notification' in window)||!('serviceWorker' in navigator)){toast('Desktop notifications are unavailable in this browser');await reportDesktopCapability();return}const permission=await Notification.requestPermission();await reportDesktopCapability();if(permission==='granted'){toast('Desktop notifications enabled');await syncDesktopDeliveries()}else toast(`Desktop notifications ${permission}`)}catch(e){toast(e.message)}});
$('#forget-device').addEventListener('click',async()=>{if(confirm('Disconnect this browser from SPARKLE?')){try{await api('/api/logout',{method:'POST',body:'{}'})}catch{}localStorage.removeItem('sparkle_session');showPair()}});
function autosize(e){e.target.style.height='auto';e.target.style.height=Math.min(e.target.scrollHeight,150)+'px'};['#hero-input','#chat-input'].forEach(s=>$(s).addEventListener('input',autosize));
const h=new Date().getHours();$('#greeting').textContent=h<12?'GOOD MORNING':h<18?'GOOD AFTERNOON':'GOOD EVENING';
if('serviceWorker' in navigator)navigator.serviceWorker.register('/service-worker.js').catch(()=>{});
async function syncEvents(){if($('#app').classList.contains('hidden')||document.hidden)return;try{const d=await api(`/api/events?after=${state.eventCursor}&limit=100`);if(d.cursor)state.eventCursor=d.cursor;if(d.events?.length)await refresh()}catch{}}
(async()=>{showApp();try{await refresh();const e=await api('/api/events?limit=1');state.eventCursor=e.cursor||0}catch{showPair()}setInterval(syncEvents,5000);setInterval(()=>!$('#app').classList.contains('hidden')&&!document.hidden&&refresh(),60000)})();
