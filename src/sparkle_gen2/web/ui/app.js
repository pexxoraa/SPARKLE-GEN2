const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const state={device:null,data:null,operations:null,deviceTargets:[],session:localStorage.getItem('sparkle_session')||'',messages:[],messageLoadSeq:0,filter:'all',eventCursor:0,desktopPermission:'unknown',refreshing:null,lastDesktopSyncAt:0};
const voice={recording:false,busy:false,waiting:false,sessionId:'',stream:null,context:null,source:null,processor:null,sink:null,buffers:[],samples:0,sampleRate:0,limitTriggered:false};
const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
function toast(message){const el=$('#toast');el.textContent=message;el.classList.remove('hidden');clearTimeout(el._t);el._t=setTimeout(()=>el.classList.add('hidden'),2800)}
async function api(path,opts={}){const headers={'Content-Type':'application/json',...(opts.headers||{})};const r=await fetch(path,{...opts,headers,credentials:'same-origin'});let data={};try{data=await r.json()}catch{}if(!r.ok)throw new Error(data.error||`Request failed (${r.status})`);return data}
function showPair(){document.body.classList.remove('ready');$('#pair-screen').classList.remove('hidden');$('#app').classList.add('hidden');$('#pair-os').value=navigator.platform||'Browser';}
function showApp(){document.body.classList.add('ready');$('#pair-screen').classList.add('hidden');$('#app').classList.remove('hidden');}
function statusClass(status){return ['COMPLETED','ONLINE','ACTIVE','CONNECTED','HEALTHY','LIVE_VERIFIED','LIVE_ACCEPTED'].includes(status)?'status':'status waiting'}
function timeText(value){if(!value)return '—';try{return new Intl.DateTimeFormat([], {dateStyle:'medium',timeStyle:'short'}).format(new Date(value))}catch{return value}}
function setView(name,{load=true}={}){if(name!=='chat'&&typeof voice!=='undefined'&&voice.mode!=='idle')stopLiveVoice(true).catch(()=>{});$$('.view').forEach(v=>v.classList.toggle('active',v.id===`view-${name}`));$$('.nav-item').forEach(v=>v.classList.toggle('active',v.dataset.view===name));$$('.mobile-nav-item').forEach(v=>v.classList.toggle('active',v.dataset.view===name));const titles={home:['PERSONAL WORKSPACE','Home'],chat:['CONTINUOUS CONTEXT','Conversation'],tasks:['ORCHESTRATION','Tasks'],['device-agent']:['DEVICE EXECUTION','Device Agent'],goals:['LONG-TERM DIRECTION','Goals'],projects:['PROJECT SPACE','Projects'],learning:['LEARNING OS','Learning'],skills:['CAPABILITY GRAPH','Skills'],research:['RESEARCH LAB','Research'],progress:['LONGITUDINAL VIEW','Progress'],approvals:['HUMAN AUTHORITY','Approvals'],devices:['TRUST BOUNDARY','Devices'],notifications:['ATTENTION','Inbox'],artifacts:['VERIFIED OUTPUTS','Artifacts'],settings:['PERSONAL CORE','Settings']};const title=titles[name]||titles.home;$('#view-eyebrow').textContent=title[0];$('#view-title').textContent=title[1];$('.sidebar').classList.remove('open');if(name==='chat'&&load)loadMessages();if(['goals','projects','learning','skills','research','progress','settings'].includes(name))loadOS().catch(e=>toast(e.message));}
function miniEmpty(text){return `<p class="muted">${esc(text)}</p>`}
function renderMarkdown(source){
  const text=String(source??'').replace(/\r\n?/g,'\n').trim();
  if(!text)return '';
  const escaped=esc(text);
  const codeBlocks=[];
  const fence='\x60\x60\x60';
  const fenced=escaped.replace(new RegExp(fence+'([^\\n]*)\\n([\\s\\S]*?)'+fence,'g'),function(_,lang,code){
    const id='@@CODE'+codeBlocks.length+'@@';
    codeBlocks.push('<pre class="md-code"><code'+(lang?' data-language="'+esc(lang.trim())+'"':'')+'>'+code.trimEnd()+'</code></pre>');
    return id;
  });
  const lines=fenced.split('\n');
  const out=[];let paragraph=[];let list=[];
  const flushParagraph=()=>{if(paragraph.length){out.push('<p>'+inlineMarkdown(paragraph.join('\n'))+'</p>');paragraph=[]}};
  const flushList=()=>{if(list.length){out.push('<ul>'+list.map(item=>'<li>'+inlineMarkdown(item)+'</li>').join('')+'</ul>');list=[]}};
  for(const line of lines){
    const trimmed=line.trim();
    if(/^@@CODE\d+@@$/.test(trimmed)){flushParagraph();flushList();out.push(trimmed);continue}
    const bullet=trimmed.match(/^[-*+]\s+(.*)$/);
    const heading=trimmed.match(/^(#{1,3})\s+(.*)$/);
    if(bullet){flushParagraph();list.push(bullet[1]);continue}
    if(heading){flushParagraph();flushList();const level=Math.min(3,heading[1].length);out.push('<h'+level+'>'+inlineMarkdown(heading[2])+'</h'+level+'>');continue}
    if(!trimmed){flushParagraph();flushList();continue}
    flushList();paragraph.push(line);
  }
  flushParagraph();flushList();
  return out.join('').replace(/@@CODE(\d+)@@/g,function(_,i){return codeBlocks[Number(i)]||''});
}
function inlineMarkdown(value){
  return value
    .replace(/\x60([^\x60\n]+)\x60/g,'<code class="md-inline-code">$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>')
    .replace(/__([^_\n]+)__/g,'<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g,'$1<em>$2</em>')
    .replace(/(^|[^_])_([^_\n]+)_(?!_)/g,'$1<em>$2</em>')
    .replace(/\n/g,'<br>');
}
function renderTaskCard(t){return `<article class="task-card"><div class="row"><div><div class="status">${esc(t.status)}</div><h3>${esc(t.goal||'Background task')}</h3></div><strong>${Number(t.progress)||0}%</strong></div><p class="muted">${esc(t.current_operation?`Current: ${t.current_operation}`:'No active operation')}</p><div class="progress"><span style="width:${Math.max(0,Math.min(100,Number(t.progress)||0))}%"></span></div></article>`}
function renderHome(){
  const ops=state.operations||{},today=ops.today||{},oper=ops.operations||{},intel=ops.intelligence||{};
  const next=ops.next_action||{};$('#home-next-action').innerHTML=next.status&&next.status!=='NONE'?`<b>${esc(next.title||'Unresolved action')}</b><br><small class="muted">${esc(next.source||'Personal Core')} · ${esc(next.status)}</small>`:`<span class="muted">Clear</span>`;
  const daily=today.daily_brief||{},brief=daily.brief||null;
  $('#home-daily').innerHTML=brief?`<b>${esc(brief.day||daily.day||'Today')}</b><br><small class="muted">${Number(daily.unresolved_count||0)} open · ${Number(daily.completed_count||0)} done</small>`:`<span class="muted">No brief persisted</span>`;
  const attention=today.attention||[];$('#home-attention').innerHTML=attention.length?`<b>${esc(attention[0].title||attention[0].kind||'Needs attention')}</b><br><small class="muted">${esc(attention[0].reason||attention[0].status||'Needs attention')}${attention.length>1?` · +${attention.length-1} more`:''}</small>`:`<span class="muted">Nothing urgent</span>`;
  const tasks=(today.active_work||[]).slice(0,3);$('#active-work').innerHTML=tasks.length?tasks.map(renderTaskCard).join(''):miniEmpty('No active tasks. Ask SPARKLE to start something.');
  const approvals=oper.pending_approvals||[];$('#home-approvals').innerHTML=approvals.length?approvals.slice(0,4).map(a=>`<div class="mini-row"><span><b>${esc(a.action)}</b><br><small class="muted">${esc(a.capability)} · ${esc(a.risk)} risk</small></span><span><button class="action approve" data-ops-approval="approve" data-id="${esc(a.approval_id)}">Approve</button> <button class="action reject" data-ops-approval="reject" data-id="${esc(a.approval_id)}">Reject</button></span></div>`).join(''):miniEmpty('Nothing is waiting for approval.');
  const devices=state.data?.devices||[];$('#home-devices').innerHTML=devices.length?devices.slice(0,4).map(d=>`<div class="mini-row"><span>${esc(d.name)}</span><span class="status">${esc(d.status)}</span></div>`).join(''):miniEmpty('No authorized clients.');
  const notes=(today.notifications||[]).slice(0,4);$('#home-notifications').innerHTML=notes.length?notes.map(n=>`<div class="mini-row"><span><b>${esc(n.title)}</b>${Number(n.occurrence_count||1)>1?` <small class="muted">×${Number(n.occurrence_count)}</small>`:''}<br><small class="muted">${esc(n.body)}</small>${n.why?`<br><small class="muted">Why: ${esc(n.why)}</small>`:''}</span><span>${esc(n.priority)}</span></div>`).join(''):miniEmpty('No recent notifications.');
  const models=(intel.capabilities?.models||[]),registry=(intel.capabilities?.registry||[]),acceptance=Object.fromEntries(registry.map(x=>[x.capability,x]));$('#home-capabilities').innerHTML=models.length?`<p class="muted">Model capabilities</p>`+models.map(x=>`<div class="mini-row"><span>${esc(x.capability==='voice'&&acceptance.voice_stt_tts?.status==='LIVE_VERIFIED'?'voice · Gemini 3.8 Live':x.capability)}</span><span class="${statusClass((x.capability==='voice'&&acceptance.voice_stt_tts?.status==='LIVE_VERIFIED')?'LIVE_ACCEPTED':x.status)}">${esc((x.capability==='voice'&&acceptance.voice_stt_tts?.status==='LIVE_VERIFIED')?'LIVE_ACCEPTED':x.status)}</span></div>`).join(''):miniEmpty('Model capability state unavailable.');
  const conns=intel.connectors||{};$('#home-connectors').innerHTML=(conns.items||[]).length?`<p class="muted">Connectors</p>`+conns.items.slice(0,6).map(x=>`<div class="mini-row"><span>${esc(x.name)}</span><span class="${x.status==='CONNECTED'?'status':'status waiting'}">${esc(x.status)}</span></div>`).join(''):`<p class="muted">Connectors: ${esc(conns.status||'UNAVAILABLE')}</p>`;
  const world=intel.world_state||{};$('#home-world').innerHTML=(world.items||[]).length?`<p class="muted">World state</p>`+world.items.slice(0,5).map(x=>`<div class="mini-row"><span>${esc(x.node_id)} · ${esc(x.kind)}</span><span class="${x.freshness==='FRESH'?'status':'status waiting'}">${esc(x.freshness)}</span></div>`).join(''):`<p class="muted">World state: ${esc(world.status||'UNAVAILABLE')}</p>`;
}
function renderTasks(){const all=state.data?.tasks||[];const filtered=all.filter(t=>state.filter==='all'||(state.filter==='active'&&!['COMPLETED','CANCELLED','FAILED','BLOCKED'].includes(t.status))||(state.filter==='waiting'&&['WAITING','BLOCKED'].includes(t.status))||(state.filter==='complete'&&t.status==='COMPLETED'));$('#task-list').innerHTML=filtered.length?filtered.map(t=>`<article class="list-card"><div class="head"><div><span class="${statusClass(t.status)}">${esc(t.status)}</span><h3>${esc(t.goal||t.goal_id)}</h3><p class="muted">${esc('Captured as a personal task')}</p></div><strong>${Number(t.progress)||0}%</strong></div><div class="progress"><span style="width:${Math.max(0,Math.min(100,Number(t.progress)||0))}%"></span></div><div class="actions"><button class="action" data-os-plan="task" data-os-id="${esc(t.goal_id)}">Plan with SPARKLE</button>${(!['COMPLETED','CANCELLED'].includes(t.status))?`<button class="action" data-task="resume" data-id="${esc(t.goal_id)}">Resume</button><button class="action danger" data-task="cancel" data-id="${esc(t.goal_id)}">Cancel</button>`:''}<button class="action danger" data-task="delete" data-id="${esc(t.goal_id)}">Delete</button></div></article>`).join(''):miniEmpty('No tasks in this view.');}
function renderApprovals(){const rows=state.data?.pending_approvals||[];$('#approval-list').innerHTML=rows.length?rows.map(a=>`<article class="list-card"><div class="head"><div><span class="status">${esc(a.risk)} RISK</span><h3>${esc(a.action)}</h3><p class="muted">Capability: ${esc(a.capability)} · Scope: ${esc(a.requested_scope)}<br>Requested ${esc(timeText(a.requested_at))}${a.expires_at?` · Expires ${esc(timeText(a.expires_at))}`:''}</p></div></div><div class="actions"><button class="action approve" data-approval="approve" data-id="${esc(a.approval_id)}">Approve</button><button class="action reject" data-approval="reject" data-id="${esc(a.approval_id)}">Reject</button></div></article>`).join(''):miniEmpty('No pending approvals.');}
function renderDevices(){const rows=state.data?.devices||[];$('#device-list').innerHTML=rows.length?rows.map(d=>`<article class="device-card"><div class="device-icon">${d.kind==='phone'?'▯':d.kind==='tablet'?'▭':'⌁'}</div><h3>${esc(d.name)}</h3><p><span class="${statusClass(d.status)}">${esc(d.status)}</span> · ${esc(d.kind)} · ${esc(d.os_name)}</p><p class="muted">Last seen ${esc(timeText(d.last_seen))}</p><div class="capabilities">${(d.capabilities||[]).map(c=>`<span class="cap">${esc(c)}</span>`).join('')}</div><div class="actions"><button class="action" data-device-rename="${esc(d.device_id)}">Rename</button>${state.device?.device_id!==d.device_id?`<button class="action danger" data-device-revoke="${esc(d.device_id)}">Revoke</button>`:''}</div></article>`).join(''):miniEmpty('No authorized devices.');}
function renderArtifacts(){const rows=[...(state.data?.artifacts||[])];$('#artifact-list').innerHTML=rows.length?rows.map(a=>`<article class="list-card"><div class="head"><div><span class="status">${esc(a.status)}</span><h3>${esc(a.project_name)}</h3><p class="muted">${esc(a.artifact_name)} · ${Number(a.artifact_bytes||0).toLocaleString()} bytes<br>SHA-256 ${esc(String(a.artifact_sha256||'').slice(0,16))}… · ${esc(timeText(a.created_at))}</p></div></div><div class="actions"><a class="action" href="/api/artifacts/${encodeURIComponent(a.artifact_id)}/download">Download verified package</a></div></article>`).join(''):miniEmpty('No generated artifacts yet.');}
function renderOSInto(containerName,name){const el=document.querySelector(containerName);if(!el)return;const os=state.os||{};if(name==='progress'){const p=os.progress||{};el.innerHTML=`<div class="os-metrics">${[['Goals completed',p.goals_completed,p.goals_total],['Tasks completed',p.tasks_completed,p.tasks_total],['Learning plans',p.learning_plans,null],['Skills tracked',p.skills_tracked,null],['Research records',p.research_records,null]].map(x=>`<article class="os-metric"><small>${esc(x[0])}</small><strong>${Number(x[1]||0)}</strong><span>${x[2]!=null?`${Number(x[1]||0)} / ${Number(x[2]||0)}`:'Tracked'}</span></article>`).join('')}</div>`;return}if(name==='settings'){const st=os.settings||{};el.innerHTML=`<div class="settings-grid"><article class="surface"><p class="eyebrow">AUTONOMY</p><h3>${esc(st.autonomy?.mode||'UNKNOWN')}</h3><p class="muted">User-owned execution ceiling.</p></article><article class="surface"><p class="eyebrow">VOICE</p><h3>${esc(st.voice?.model||'Unavailable')}</h3><p class="muted">${esc(st.voice?.operation||'Voice capability')}</p></article></div>`;return}const dataKey={goals:'goals',projects:'projects',learning:'learning_plans',skills:'skills',research:'research'}[name]||name;const rows=Array.isArray(os[dataKey])?os[dataKey]:[];if(!rows.length){el.innerHTML=`<div class="os-empty"><span>✦</span><strong>No ${esc(name)} records yet.</strong><p>The Personal Core has no persisted ${esc(name)} data to display.</p></div>`;return}el.innerHTML=rows.map(item=>{const title=item.title||item.subject||item.name||item.hypothesis||item.goal||item.skill_id||item.project_id||'Record';const status=item.status||item.verification_state||'PERSISTED';const detail=item.objective||item.method||(item.experiment_count!=null?`${item.experiment_count} experiment${item.experiment_count===1?'':'s'}`:'');const deleteControl=name==='goals'&&item.goal_id?`<div class="actions"><button class="action" data-os-plan="goal" data-os-id="${esc(item.goal_id)}">Plan with SPARKLE</button><button class="action danger" data-goal-delete="${esc(item.goal_id)}">Delete goal</button></div>`:name==='learning'&&item.plan_id?`<div class="actions"><button class="action" data-os-plan="learning" data-os-id="${esc(item.plan_id)}">Plan with SPARKLE</button></div>`:['projects','skills','research'].includes(name)?`<div class="actions"><button class="action" data-os-plan="${esc(name)}" data-os-id="${esc(item.record_id||'')}">Plan with SPARKLE</button><button class="action danger" data-os-record-delete="${esc(item.record_id||'')}">Delete</button></div>`:'';return `<article class="list-card os-record"><div class="head"><div><span class="${statusClass(status)}">${esc(status)}</span><h3>${esc(title)}</h3><p class="muted">${esc(String(detail||'').slice(0,500))}</p></div>${item.progress!=null?`<strong>${Number(item.progress)}%</strong>`:''}</div>${item.progress!=null?`<div class="progress"><span style="width:${Math.max(0,Math.min(100,Number(item.progress)||0))}%"></span></div>`:''}${item.best_score!=null?`<div class="os-score">Best score · ${Math.round(Number(item.best_score)*100)}%</div>`:''}${deleteControl}</article>`}).join('')}
async function loadOS(){state.os=await api('/api/os');['goals','projects','learning','skills','research','progress','settings'].forEach(name=>renderOSInto(name==='goals'?'#os-list':'#os-list-'+name,name))}
function renderDeviceAgent(){const select=$('#device-agent-target');if(!select)return;const devices=state.deviceTargets||[];select.innerHTML=devices.length?devices.map(d=>'<option value="'+esc(d.target_id)+'">'+esc(d.name||d.target_id)+' · '+esc(d.kind||'device')+'</option>').join(''):'<option value="">No available execution targets</option>';if(state.device){const preferred=devices.find(d=>d.device_id===state.device.device_id&&d.kind==='linux')||devices.find(d=>d.device_id===state.device.device_id);if(preferred)select.value=preferred.target_id}}
async function loadDeviceAgentTargets(){try{const data=await api('/api/device-agent/targets');state.deviceTargets=Array.isArray(data.targets)?data.targets:[];renderDeviceAgent()}catch(error){state.deviceTargets=[];renderDeviceAgent();throw error}}
async function runDeviceAgent(){const target=$('#device-agent-target')?.value?.trim(),command=$('#device-agent-command')?.value?.trim(),status=$('#device-agent-status'),resultBox=$('#device-agent-result');if(!target||!command){toast('Choose a device and enter a command.');return}status.textContent='Creating task…';resultBox.innerHTML='<div class="activity"><span class="activity-orb"></span><span>Planning for target device…</span></div>';try{const result=await api('/api/chat',{method:'POST',body:JSON.stringify({text:command,target_device_id:target,device_id:state.device?.device_id})});state.session=result.session_id;localStorage.setItem('sparkle_session',state.session);const msg=result.message||{},body=result.result||{};status.textContent=msg.status==='WAITING'?'Waiting for approval.':'Task processed.';resultBox.innerHTML='<div class="device-result-state"><span class="'+statusClass(msg.status||'COMPLETED')+'">'+esc(msg.status||'COMPLETED')+'</span><h4>'+esc(body.goal_id||'Task created')+'</h4><div>'+renderMarkdown(msg.text||'No result returned.')+'</div><small class="muted">Target device · '+esc(target)+'</small></div>';await refresh()}catch(error){status.textContent='Task failed.';resultBox.innerHTML='<div class="os-empty"><strong>Could not create device task.</strong><p>'+esc(error.message)+'</p></div>'}}
function renderNotifications(){const rows=[...(state.data?.notifications||[])].reverse();$('#notification-list').innerHTML=rows.length?rows.map(n=>`<article class="list-card"><div class="head"><div><span class="status">${esc(n.priority)}${n.decision?` · ${esc(n.decision)}`:''}</span><h3>${esc(n.title)}${Number(n.occurrence_count||1)>1?` <small class="muted">×${Number(n.occurrence_count)}</small>`:''}</h3><p class="muted">${esc(n.body)}${n.why?`<br>Why: ${esc(n.why)}`:''}<br>${esc(timeText(n.created_at))}</p></div><span>${esc(n.status)}</span></div>${n.status==='UNREAD'?`<div class="actions"><button class="action" data-note-read="${esc(n.notification_id)}">Mark read</button></div>`:''}</article>`).join(''):miniEmpty('No notifications.');}
function renderSessions(){const picker=$('#session-picker');const button=$('#delete-session');const rows=state.data?.sessions||[];if(state.session&&!rows.some(s=>s.session_id===state.session))state.session='';picker.innerHTML=`<option value="">New conversation</option>`+rows.map(s=>`<option value="${esc(s.session_id)}" ${s.session_id===state.session?'selected':''}>${esc(s.title||'Conversation')} · ${Number(s.message_count||0)} turns</option>`).join('');picker.value=state.session||'';if(button)button.disabled=!state.session;}
async function deleteCurrentConversation(){if(!state.session){toast('Select a conversation history entry first.');return}const sid=state.session;if(!confirm('Delete this conversation history permanently?'))return;await api(`/api/sessions/${encodeURIComponent(sid)}/delete`,{method:'POST',body:'{}'});state.messageLoadSeq++;state.session='';state.messages=[];localStorage.removeItem('sparkle_session');renderSessions();renderMessages();await refresh();toast('Conversation history deleted')}
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
      renderDeviceAgent();
      renderSessions();
      loadDeviceAgentTargets().catch(()=>{});
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

function audioContextClass(){return window.AudioContext||window.webkitAudioContext||null}
function voiceSupported(){return !!(navigator.mediaDevices?.getUserMedia&&audioContextClass())}
const LIVE_FRAME_MS=250,LIVE_SILENCE_MS=900,LIVE_SPEECH_START_MS=120,LIVE_MIN_TURN_MS=280,LIVE_BARGE_IN_MS=320,LIVE_ECHO_IGNORE_MS=450,LIVE_POST_SPEAK_IGNORE_MS=500,LIVE_RMS_FLOOR=0.008,LIVE_RMS_MULTIPLIER=2.2,LIVE_PREROLL_MS=450;
voice.mode='idle';voice.userSpeaking=false;voice.turnStartedAt=0;voice.lastSpeechAt=0;voice.turnSamples=0;voice.turnId=0;voice.speechCandidateAt=0;voice.noiseFloor=LIVE_RMS_FLOOR;voice.streamBuffers=[];voice.streamSamples=0;voice.sendQueue=Promise.resolve();voice.streamError=null;voice.pendingInterrupt=false;voice.playbackSource=null;voice.liveTranscript='';voice.preRoll=[];voice.speakingStartedAt=0;voice.speakingEndedAt=0;voice.bargeInStartedAt=0;
function liveVoiceSetState(mode,label){
  voice.mode=mode;const panel=$('#live-voice-panel'),orb=$('#live-voice-orb'),stateEl=$('#live-voice-state');
  if(panel)panel.classList.remove('hidden');
  if(orb)orb.dataset.state=mode;
  if(stateEl)stateEl.textContent=label;
  const button=$('#voice-button');if(button){button.classList.toggle('recording',mode!=='idle'&&mode!=='stopping');button.textContent=mode==='idle'?'◉':'■';}
}
function renderVoiceStructure(source){
  let value=String(source||'').replace(/\r\n?/g,'\n').trim();
  if(!value)return '';
  value=value.replace(/```/g,'').replace(/\*/g,'').replace(/`/g,'').replace(/[{}]/g,'');
  const lines=value.split('\n');
  const sections=[];let current=null;
  for(const raw of lines){
    const line=raw.trim();if(!line)continue;
    const match=line.match(/^(\d+)[.)]\s+(.*)$/);
    if(match){current={title:match[1]+'. '+match[2],body:''};sections.push(current);continue}
    if(current)current.body+=(current.body?' ':'')+line;else sections.push({title:'',body:line});
  }
  if(sections.length<2)return '<div class=\"voice-plain\">'+esc(value)+'</div>';
  return sections.map((section,index)=>'<div class=\"voice-section\">'+(section.title?'<strong>'+esc(section.title)+'</strong>':'<strong>Part '+(index+1)+'</strong>')+'<p>'+esc(section.body)+'</p></div>').join('');
}

function renderLiveVoiceContext(){
  const el=$('#live-voice-context-list');if(!el)return;
  const rows=(state.messages||[]).slice(-8);
  el.innerHTML=rows.length?rows.map(m=>'<div class="voice-context-message '+esc(m.role)+'"><span>'+esc(m.role==='assistant'?'SPARKLE':'YOU')+'</span><p>'+renderPlainText(m.text)+'</p></div>').join(''):'<p class="muted">No previous messages in this conversation.</p>';
  el.scrollTop=el.scrollHeight;
}
function liveVoiceShowTranscript(text){
  const el=$('#live-voice-transcript');if(!el)return;
  const value=String(text||'');el.innerHTML=value.trim()?renderVoiceStructure(value):'';el.classList.toggle('hidden',!value.trim());
  renderLiveVoiceContext();
}
function updateVoiceButton(){
  const button=$('#voice-button');if(!button)return;
  const supported=voiceSupported(),active=voice.mode!=='idle';
  button.disabled=!supported||voice.busy||voice.waiting;
  button.classList.toggle('recording',active);
  button.textContent=active?'■':'◉';
  const label=!supported?'Voice capture is unavailable in this browser':voice.waiting?'Voice action is waiting for approval':active?'End live voice conversation':'Start live voice conversation';
  button.title=label;button.setAttribute('aria-label',label);
}
function detachVoiceCapture(closeContext=true){
  const context=voice.context;
  try{if(voice.processor)voice.processor.onaudioprocess=null}catch{}
  try{voice.source?.disconnect()}catch{}
  try{voice.processor?.disconnect()}catch{}
  try{voice.sink?.disconnect()}catch{}
  try{voice.stream?.getTracks().forEach(track=>track.stop())}catch{}
  voice.stream=null;voice.source=null;voice.processor=null;voice.sink=null;voice.context=null;voice.speakingEndedAt=0;
  if(closeContext&&context&&context.state!=='closed')context.close().catch(()=>{});
  return context;
}
function resampleVoicePcm16(buffers,sourceRate){
  const total=buffers.reduce((n,b)=>n+b.length,0);
  if(!Number.isFinite(sourceRate)||sourceRate<=0||total<=0)throw new Error('No microphone audio was captured');
  if(total>sourceRate*30)throw new Error('Voice turns are limited to 30 seconds');
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
function floatRms(input){let sum=0;for(let i=0;i<input.length;i++){const v=input[i];sum+=v*v}return Math.sqrt(sum/Math.max(1,input.length))}
function base64ToBytes(text){const raw=atob(String(text||'')),out=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)out[i]=raw.charCodeAt(i);return out}
async function speakVoiceFallback(text){
  const value=String(text||'').replace(/^ANSWER_REQUEST:\s*/,'').trim();
  if(!value)return false;
  if(!('speechSynthesis' in window)||typeof SpeechSynthesisUtterance==='undefined')return false;
  try{
    window.speechSynthesis.cancel();
    const utterance=new SpeechSynthesisUtterance(value);utterance.rate=1.02;utterance.pitch=1;
    voice.speakingStartedAt=Date.now();voice.speakingEndedAt=0;liveVoiceSetState('speaking','SPARKLE is speaking…');
    return await new Promise(resolve=>{utterance.onend=()=>{voice.speakingEndedAt=Date.now();resolve(true)};utterance.onerror=()=>{voice.speakingEndedAt=Date.now();resolve(false)};window.speechSynthesis.speak(utterance)})
  }catch{return false}
}
function decodeVoiceAudio(chunks){
  const rows=[...(chunks||[])].sort((a,b)=>(Number(a.sequence)||0)-(Number(b.sequence)||0));if(!rows.length)return null;
  let total=0;const decoded=[];
  for(const row of rows){
    if(row.sample_rate!==24000||row.channels!==1||row.sample_width!==2||row.encoding!=='pcm_s16le'||!row.audio_base64)throw new Error('Voice response audio format is invalid');
    const bytes=base64ToBytes(row.audio_base64);if(!bytes.length||bytes.length%2)throw new Error('Voice response audio is malformed');
    total+=bytes.length;if(total>4000000)throw new Error('Voice response audio exceeds the browser playback limit');decoded.push(bytes);
  }
  return {rows,decoded,total};
}
async function playVoiceChunks(chunks,context=null){
  const decoded=decodeVoiceAudio(chunks);if(!decoded)return false;const Ctx=audioContextClass();if(!Ctx)throw new Error('Audio playback is unavailable in this browser');
  const own=!context,ctx=context||new Ctx();if(ctx.state==='suspended')await ctx.resume();
  const samples=decoded.total/2,buffer=ctx.createBuffer(1,samples,24000),channel=buffer.getChannelData(0);let cursor=0;
  for(const bytes of decoded.decoded){const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);for(let i=0;i<bytes.length;i+=2)channel[cursor++]=view.getInt16(i,true)/32768}
  const source=ctx.createBufferSource();source.buffer=buffer;source.connect(ctx.destination);
  await new Promise((resolve,reject)=>{source.onended=resolve;try{source.start()}catch(error){reject(error)}});
  try{source.disconnect()}catch{}if(own&&ctx.state!=='closed')await ctx.close();return true;
}
function liveQueuePcm(pcm,final=false){
  if(!pcm?.length)return Promise.resolve();
  const send=async()=>{for(let offset=0;offset<pcm.length;offset+=48000){
    const part=pcm.subarray(offset,Math.min(offset+48000,pcm.length));
    const isFinal=final&&offset+48000>=pcm.length;
    await api('/api/voice/sessions/'+encodeURIComponent(voice.sessionId)+'/audio',{method:'POST',body:JSON.stringify({audio_base64:bytesToBase64(part),sequence:voice.nextSequence++,final:isFinal})}).then(async response=>{if(isFinal)await handleLiveVoiceResponse(response)});
  }};
  voice.sendQueue=voice.sendQueue.catch(()=>{}).then(send);return voice.sendQueue;
}
function pushLiveFloatChunk(input){
  const copy=new Float32Array(input);voice.streamBuffers.push(copy);voice.streamSamples+=copy.length;
  const target=Math.max(1,Math.floor(voice.sampleRate*LIVE_FRAME_MS/1000));
  if(voice.streamSamples<target)return;
  const parts=[];let remaining=target;
  while(remaining>0&&voice.streamBuffers.length){const part=voice.streamBuffers[0];if(part.length<=remaining){parts.push(part);voice.streamBuffers.shift();voice.streamSamples-=part.length;remaining-=part.length}else{parts.push(part.subarray(0,remaining));voice.streamBuffers[0]=part.subarray(remaining);voice.streamSamples-=remaining;remaining=0}}
  const pcm=resampleVoicePcm16(parts,voice.sampleRate);liveQueuePcm(pcm,false);
}
function takeBufferedLiveAudio(){
  const parts=voice.streamBuffers.slice();voice.streamBuffers=[];voice.streamSamples=0;
  return parts.length?resampleVoicePcm16(parts,voice.sampleRate):new Uint8Array();
}
async function syncVoiceConversation(sessionId){
  const inspected=await api('/api/voice/sessions/'+encodeURIComponent(sessionId));
  const conversation=inspected.session?.conversation_session_id;
  if(conversation){state.session=conversation;localStorage.setItem('sparkle_session',conversation)}
  renderLiveVoiceContext();
  return inspected;
}
async function closeVoiceSession(sessionId){if(!sessionId)return;try{await api('/api/voice/sessions/'+encodeURIComponent(sessionId)+'/close',{method:'POST',body:'{}'})}catch{}}
async function interruptLiveVoice(){
  if(!voice.sessionId||voice.pendingInterrupt)return;
  voice.pendingInterrupt=true;try{if(voice.playbackSource){try{voice.playbackSource.stop()}catch{}voice.playbackSource=null}
    await api('/api/voice/sessions/'+encodeURIComponent(voice.sessionId)+'/interrupt',{method:'POST',body:'{}'});
    voice.turnStartedAt=0;voice.lastSpeechAt=Date.now();voice.turnSamples=0;voice.streamBuffers=[];voice.streamSamples=0;voice.userSpeaking=false;voice.bargeInStartedAt=0;
    liveVoiceSetState('listening','Listening…');liveVoiceShowTranscript('');
  }catch(error){liveVoiceSetState('error','Voice interruption failed');toast(error.message)}finally{voice.pendingInterrupt=false}
}
async function handleLiveVoiceResponse(response){
  if(response?.session_id){
    await syncVoiceConversation(response.session_id).catch(()=>{});
    loadMessages().then(renderLiveVoiceContext).catch(()=>renderLiveVoiceContext());
  }
  const rows=Array.isArray(response?.transcripts)?response.transcripts:[];
  const assistant=rows.filter(x=>x.speaker==='assistant').map(x=>x.text).filter(Boolean).join(' ');
  const user=rows.filter(x=>x.speaker==='user').map(x=>x.text).filter(Boolean).join(' ');
  liveVoiceShowTranscript(assistant||user||'');
  if(response?.agent_result?.status==='WAITING'){
    voice.waiting=true;voice.mode='waiting';liveVoiceSetState('waiting','Waiting for your approval');toast('Voice action is waiting for your approval');return;
  }
  if(!response?.audio_chunks?.length){
    const fallbackText=response?.agent_result?.text||'';
    const fallback=response?.agent_result?.voice_tts_fallback||response?.agent_result?.voice_retry;
    if(fallback&&fallbackText){liveVoiceShowTranscript(fallbackText);await speakVoiceFallback(fallbackText);if(voice.mode!=='waiting'&&voice.mode!=='stopping'){liveVoiceShowTranscript('');liveVoiceSetState('listening','Listening…')}return}
    liveVoiceSetState('listening','Listening…');return
  }
  liveVoiceSetState('speaking','SPARKLE is speaking…');
  voice.speakingStartedAt=Date.now();voice.bargeInStartedAt=0;
  const decoded=decodeVoiceAudio(response.audio_chunks);if(!decoded)throw new Error('Voice provider returned no authorized response audio');
  const Ctx=audioContextClass();if(!Ctx)throw new Error('Audio playback is unavailable in this browser');
  const ctx=voice.context||new Ctx();if(ctx.state==='suspended')await ctx.resume();
  const samples=decoded.total/2,buffer=ctx.createBuffer(1,samples,24000),channel=buffer.getChannelData(0);let cursor=0;
  for(const bytes of decoded.decoded){const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);for(let i=0;i<bytes.length;i+=2)channel[cursor++]=view.getInt16(i,true)/32768}
  const source=ctx.createBufferSource();source.buffer=buffer;source.connect(ctx.destination);voice.playbackSource=source;
  await new Promise((resolve,reject)=>{source.onended=resolve;try{source.start()}catch(error){reject(error)}});
  voice.playbackSource=null;voice.speakingEndedAt=Date.now();
  if(voice.mode!=='waiting'&&voice.mode!=='stopping'){liveVoiceShowTranscript('');liveVoiceSetState('listening','Listening…')}
}
async function beginLiveTurn(){
  if(voice.mode!=='listening'||!voice.userSpeaking||voice.turnSamples<=0)return;
  const durationMs=(Date.now()-voice.turnStartedAt),turnId=voice.turnId;if(durationMs<LIVE_MIN_TURN_MS)return;
  voice.userSpeaking=false;voice.mode='thinking';liveVoiceSetState('thinking','Thinking…');
  const finalPcm=takeBufferedLiveAudio();const silence=new Uint8Array(24000*0.04*2);
  try{
    await liveQueuePcm(finalPcm,false);
    voice.sendQueue=voice.sendQueue.catch(()=>{}).then(()=>api('/api/voice/sessions/'+encodeURIComponent(voice.sessionId)+'/audio',{method:'POST',body:JSON.stringify({audio_base64:bytesToBase64(silence),sequence:voice.nextSequence++,final:true})}).then(handleLiveVoiceResponse));
    await voice.sendQueue;
    if(voice.turnId===turnId&&voice.mode!=='speaking'&&voice.mode!=='waiting'){voice.turnStartedAt=0;voice.turnSamples=0;}
  }catch(error){
    try{if(voice.sessionId)await api('/api/voice/sessions/'+encodeURIComponent(voice.sessionId)+'/interrupt',{method:'POST',body:'{}'})}catch{}
    voice.userSpeaking=false;voice.turnStartedAt=0;voice.turnSamples=0;voice.streamBuffers=[];voice.streamSamples=0;voice.bargeInStartedAt=0;liveVoiceSetState('listening','Voice recovered — Listening…');toast('Voice recovered. Please continue speaking.')
  }
}
function handleLiveMic(input){
  const rms=floatRms(input),nowMs=Date.now();
  // Adapt to the device microphone instead of using one absolute threshold.
  // Quiet speech on phones can be well below 0.025 RMS, while fans/background
  // noise can sit above it. Track the floor only while the user is not speaking.
  if(!voice.userSpeaking&&voice.mode==='listening'){
    const floor=Math.max(LIVE_RMS_FLOOR,Math.min(0.08,rms));
    voice.noiseFloor=voice.noiseFloor*0.92+floor*0.08;
  }
  const threshold=Math.max(LIVE_RMS_FLOOR,voice.noiseFloor*LIVE_RMS_MULTIPLIER);
  const speech=rms>=threshold;
  const frame=new Float32Array(input);voice.preRoll.push(frame);voice.preRoll=voice.preRoll.slice(-Math.max(1,Math.floor(voice.sampleRate*LIVE_PREROLL_MS/1000/4096)+1));
  if(voice.mode==='speaking'){
    // Do not sample barge-in while SPARKLE is speaking. Speaker leakage/echo
    // must never become a new user turn (for example: “Hello. ¿Qué?”).
    voice.bargeInStartedAt=0;return;
  }
  if(voice.mode!=='listening')return;
  if(voice.speakingEndedAt&&nowMs-voice.speakingEndedAt<LIVE_POST_SPEAK_IGNORE_MS)return;
  pushLiveFloatChunk(input);
  if(speech){
    if(!voice.userSpeaking){voice.userSpeaking=true;voice.turnId++;voice.turnStartedAt=nowMs;voice.turnSamples=0;liveVoiceShowTranscript('');}
    voice.lastSpeechAt=nowMs;voice.turnSamples+=frame.length;
  }else if(voice.userSpeaking&&nowMs-voice.lastSpeechAt>=LIVE_SILENCE_MS){
    beginLiveTurn();
  }
}
async function startLiveVoice(){
  if(voice.mode!=='idle'||voice.busy||voice.waiting)return;
  if(!voiceSupported())throw new Error('Microphone capture is unavailable in this browser');
  voice.busy=true;updateVoiceButton();let opened='';
  try{
    const health=await api('/api/voice/status');if(health.status!=='HEALTHY'||!health.live_verified)throw new Error(health.reason||'Voice provider is not live verified');
    const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
    const Ctx=audioContextClass(),context=new Ctx();await context.resume();
    voice.stream=stream;voice.context=context;voice.sampleRate=context.sampleRate;voice.buffers=[];voice.samples=0;voice.limitTriggered=false;voice.nextSequence=0;voice.streamBuffers=[];voice.streamSamples=0;voice.sendQueue=Promise.resolve();voice.userSpeaking=false;voice.turnStartedAt=0;voice.lastSpeechAt=0;voice.turnSamples=0;voice.turnId=0;voice.speechCandidateAt=0;voice.noiseFloor=LIVE_RMS_FLOOR;voice.waiting=false;voice.streamError=null;voice.preRoll=[];voice.speakingStartedAt=0;voice.speakingEndedAt=0;voice.bargeInStartedAt=0;
    const started=await api('/api/voice/sessions',{method:'POST',body:JSON.stringify({conversation_session_id:state.session||null,classification:'PRIVATE',persist_transcript:true})});
    if(started.state!=='CONNECTED')throw new Error(started.failure_reason||'Live voice session could not connect');
    opened=started.session_id;voice.sessionId=opened;voice.mode='listening';liveVoiceSetState('listening','Listening…');liveVoiceShowTranscript('');
    loadMessages().then(renderLiveVoiceContext).catch(()=>renderLiveVoiceContext());
    const source=context.createMediaStreamSource(stream),processor=context.createScriptProcessor(4096,1,1),sink=context.createGain();sink.gain.value=0;
    voice.source=source;voice.processor=processor;voice.sink=sink;processor.onaudioprocess=event=>{if(voice.mode==='idle'||voice.mode==='stopping'||voice.mode==='thinking'||voice.mode==='waiting')return;try{handleLiveMic(event.inputBuffer.getChannelData(0))}catch(error){voice.streamError=error;toast(error.message)}};
    source.connect(processor);processor.connect(sink);sink.connect(context.destination);
    $('#live-voice-panel')?.classList.remove('hidden');
  }catch(error){detachVoiceCapture(true);if(opened)await closeVoiceSession(opened);voice.sessionId='';voice.mode='idle';voice.waiting=false;liveVoiceSetState('idle','');$('#live-voice-panel')?.classList.add('hidden');throw error}
  finally{voice.busy=false;updateVoiceButton()}
}
async function stopLiveVoice(force=false){
  if(voice.mode==='idle'&&!voice.sessionId)return;
  voice.mode='stopping';liveVoiceSetState('stopping','Closing live voice…');
  const sessionId=voice.sessionId;voice.userSpeaking=false;
  if(voice.playbackSource){try{voice.playbackSource.stop()}catch{}voice.playbackSource=null}
  detachVoiceCapture(false);voice.streamBuffers=[];voice.streamSamples=0;
  if(sessionId)await closeVoiceSession(sessionId);
  voice.sessionId='';voice.waiting=false;voice.mode='idle';voice.nextSequence=0;voice.sendQueue=Promise.resolve();voice.speakingStartedAt=0;voice.bargeInStartedAt=0;
  $('#live-voice-panel')?.classList.add('hidden');liveVoiceShowTranscript('');updateVoiceButton();
  if(!force){await refresh().catch(()=>{});setView('chat',{load:false});await loadMessages().catch(()=>{})}
}
function prepareVoicePlaybackContext(){const Ctx=audioContextClass();if(!Ctx)return null;try{const context=new Ctx();context.resume().catch(()=>{});return context}catch{return null}}
async function toggleVoice(){if(voice.mode!=='idle')return stopLiveVoice();return startLiveVoice()}
async function handleVoicePayload(payload,context=null){
  const rows=Array.isArray(payload?.voice)?payload.voice:[];let played=false;
  for(const row of rows){if(row.session_id){try{await syncVoiceConversation(row.session_id)}catch{}}
    if(row.audio_chunks?.length)played=(await playVoiceChunks(row.audio_chunks,context))||played;
  }
  return played;
}
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

function osEditorField(name,label,type='text',extra=''){return '<label class="field"><span>'+esc(label)+'</span><'+type+' name="'+esc(name)+'" '+extra+'></'+type+'></label>'}
function osEditorOpen(kind){
  const modal=$('#os-editor'),fields=$('#os-editor-fields'),title=$('#os-editor-title'),kicker=$('#os-editor-kicker'),error=$('#os-editor-error');if(!modal||!fields)return;
  const configs={
    task:{kicker:'EXECUTION · TASK',title:'Add task',html:osEditorField('title','Task','input','maxlength="500" required placeholder="e.g. Finish C++ OOP revision"')},
    goal:{kicker:'EXECUTION · GOAL',title:'Add goal',html:osEditorField('title','Goal','input','maxlength="300" required placeholder="Outcome you want to achieve"')+osEditorField('description','Why / context','textarea','maxlength="600" rows="3" placeholder="What does success look like?"')+osEditorField('priority','Priority (1–10)','input','type="number" min="1" max="10" value="5"')+osEditorField('deadline','Deadline','input','type="date"')},
    project:{kicker:'EXECUTION · PROJECT',title:'Add project',html:osEditorField('title','Project name','input','maxlength="300" required placeholder="Project name"')+osEditorField('description','Description','textarea','maxlength="1000" rows="4" placeholder="Purpose, scope, expected outcome"')+osEditorField('goal_id','Linked goal ID (optional)','input','maxlength="100" placeholder="Paste an existing goal ID"')},
    learning:{kicker:'KNOWLEDGE · LEARNING',title:'Add learning plan',html:osEditorField('subject','Subject','input','maxlength="160" required placeholder="e.g. Python"')+osEditorField('objective','Learning objective','textarea','maxlength="500" rows="3" required placeholder="What should you master?"')+osEditorField('units','Units (one per line)','textarea','rows="7" required placeholder="Variables\\nFunctions\\nOOP\\nFile handling"')},
    skill:{kicker:'KNOWLEDGE · SKILL',title:'Add skill',html:osEditorField('title','Skill','input','maxlength="300" required placeholder="e.g. Python programming"')+osEditorField('description','Description','textarea','maxlength="1000" rows="3" placeholder="What capability does this represent?"')+osEditorField('level','Current level','input','maxlength="80" placeholder="Beginner / Intermediate / Advanced"')},
    research:{kicker:'KNOWLEDGE · RESEARCH',title:'Add research',html:osEditorField('title','Research topic','input','maxlength="300" required placeholder="Research topic"')+osEditorField('question','Research question','textarea','maxlength="1000" rows="3" placeholder="What are you trying to discover?"')+osEditorField('hypothesis','Hypothesis','textarea','maxlength="1000" rows="3" placeholder="Your current hypothesis"')+osEditorField('method','Method','textarea','maxlength="1000" rows="3" placeholder="How will you investigate it?"')+osEditorField('project_id','Linked project ID (optional)','input','maxlength="100" placeholder="Project ID"')}
  };
  const cfg=configs[kind];if(!cfg)return;
  modal.classList.remove('hidden');modal.setAttribute('aria-hidden','false');fields.querySelector('input,textarea')?.focus();
}
function osEditorClose(){const modal=$('#os-editor');if(modal){modal.classList.add('hidden');modal.setAttribute('aria-hidden','true')}}
async function osEditorSubmit(event){
  event.preventDefault();const modal=$('#os-editor'),form=event.currentTarget,kind=modal.dataset.kind,error=$('#os-editor-error');error.textContent='';
  const fd=new FormData(form),title=String(fd.get('title')||'').trim();
  try{
    let path='',body={};
    if(kind==='task'){path='/api/os/tasks';body={title}}
    else if(kind==='goal'){path='/api/os/goals';body={title,description:String(fd.get('description')||''),priority:Number(fd.get('priority')||5),deadline:String(fd.get('deadline')||'')}}
    else if(kind==='learning'){path='/api/os/learning';body={subject:String(fd.get('subject')||''),objective:String(fd.get('objective')||''),units:String(fd.get('units')||'').split(/\n+/).map(x=>x.trim()).filter(Boolean)}}
    else {path='/api/os/records';body={record_type:kind,title,description:String(fd.get('description')||''),status:'ACTIVE',metadata:{question:String(fd.get('question')||''),hypothesis:String(fd.get('hypothesis')||''),method:String(fd.get('method')||''),level:String(fd.get('level')||''),goal_id:String(fd.get('goal_id')||''),project_id:String(fd.get('project_id')||'')}}}
    const result=await api(path,{method:'POST',body:JSON.stringify(body)});
    osEditorClose();await refresh();const view=kind==='task'?'tasks':kind==='goal'?'goals':kind==='learning'?'learning':kind==='skill'?'skills':'research';setView(view,{load:false});await loadOS();toast(result.text||('Added '+kind));
  }catch(e){error.textContent=e.message}
}
async function planOSItem(kind,id){
  if(!kind||!id)return;
  const button=document.activeElement;if(button?.dataset)button.disabled=true;
  try{
    const result=await api('/api/os/plan',{method:'POST',body:JSON.stringify({record_type:kind,record_id:id})});
    await refresh();if(['project','research','skill'].includes(kind))await loadOS();
    if(result.status==='WAITING')toast('Plan created; waiting for your approval.');
    else toast('SPARKLE planned the work and linked it to this item.');
  }catch(e){toast(e.message)}
  finally{if(button?.dataset)button.disabled=false}
}
$('#pair-form').addEventListener('submit',async e=>{e.preventDefault();$('#pair-error').textContent='';try{const caps=['conversation','notifications','approvals','task_status','device_management','artifacts'];const d=await api('/api/enroll',{method:'POST',body:JSON.stringify({code:$('#pair-code').value.trim(),name:$('#pair-name').value.trim(),kind:$('#pair-kind').value,os:$('#pair-os').value.trim(),capabilities:caps,client:'web'})});state.device=d.device;showApp();await refresh()}catch(err){$('#pair-error').textContent=err.message}});
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
