/* Personal OS inspection surfaces use authoritative records and existing action gates. */
function workspaceEmpty(message){return `<article class="surface"><p class="muted">${esc(message)}</p></article>`}
function workspaceCard(title,status,body,actions=''){return `<article class="list-card"><div class="head"><div><span class="${statusClass(status)}">${esc(status)}</span><h3>${esc(title)}</h3></div></div>${body}${actions?`<div class="actions">${actions}</div>`:''}</article>`}
function workspaceRelationships(graph){
  const names=new Map((graph.nodes||[]).map(n=>[n.id,n.title||n.id]));
  const edges=(graph.edges||[]).slice(0,40);
  if(!edges.length)return workspaceEmpty('Relationships appear as work is planned and verified.');
  return `<article class="surface"><h3>Connected work</h3><div class="workspace-table-wrap"><table class="workspace-table"><thead><tr><th>From</th><th>Relationship</th><th>To</th></tr></thead><tbody>${edges.map(e=>`<tr><td>${esc(names.get(e.from)||e.from)}</td><td>${esc(e.type.replaceAll('_',' '))}</td><td>${esc(names.get(e.to)||e.to)}</td></tr>`).join('')}</tbody></table></div></article>`;
}
function workspaceExecutions(data){
  const rows=data.executions||[];
  if(!rows.length)return workspaceEmpty('No executions yet. Ask SPARKLE to perform a task.');
  return rows.map(r=>{
    const terminal=['COMPLETED','CANCELLED'].includes(r.status);
    let actions=`<button class="action" data-execution-inspect="${esc(r.goal_id)}">Inspect</button>`;
    if(r.plan_id&&!terminal){
      actions+=`<button class="action" data-execution-control="${r.run_status==='PAUSED'?'resume':'pause'}" data-goal-id="${esc(r.goal_id)}">${r.run_status==='PAUSED'?'Resume':'Pause'}</button>`;
      if(r.status==='BLOCKED')actions+=`<button class="action" data-execution-control="replan" data-goal-id="${esc(r.goal_id)}">Replan</button>`;
    }
    if(!r.plan_id&&r.run_status==='CAPTURED')actions+=`<button class="action" data-os-plan="task" data-os-id="${esc(r.goal_id)}">Plan with SPARKLE</button>`;
    if(!r.plan_id&&r.run_status!=='CAPTURED'&&!terminal)actions+=`<button class="action" data-execution-control="retry" data-goal-id="${esc(r.goal_id)}">Retry planning</button>`;
    if(!terminal)actions+=`<button class="action danger" data-execution-control="cancel" data-goal-id="${esc(r.goal_id)}">Cancel</button>`;
    return workspaceCard(r.title,r.run_status,`<p class="muted">${Number(r.completed_steps)} verified steps · ${Number(r.pending_steps)} pending · ${Number(r.iterations)} actions · ${Number(r.active_runtime_seconds).toFixed(2)} seconds of execution</p><p class="muted">Updated ${esc(timeText(r.updated_at))}</p>`,actions);
  }).join('');
}
function workspaceMemory(data){
  const rows=data.candidates||[];
  if(!rows.length)return workspaceEmpty('No memory candidates. SPARKLE proposes useful facts after verified work.');
  return rows.map(m=>{
    const id=esc(m.candidate_id);
    const actions=m.state==='PROPOSED'?`<button class="action approve" data-memory-decision="approve" data-id="${id}">Review for storage</button><button class="action reject" data-memory-decision="reject" data-id="${id}">Reject</button>`:(m.state.includes('WAITING')?`<button class="action" data-memory-decision="reconcile" data-id="${id}">Check review status</button>`:'');
    return workspaceCard(m.category||'Memory',m.state,`<p>${esc(m.value)}</p><p class="muted">${esc(m.reason)} · ${esc(m.privacy_classification)}</p>`,actions);
  }).join('');
}
function workspaceKnowledge(data,graph){
  const docs=data.documents||[],evidence=data.evidence||[];
  return (docs.length?docs.map(d=>workspaceCard(d.filename,d.status,`<p class="muted">${esc(d.classification)} · ${esc(timeText(d.updated_at||d.created_at))}</p>`)).join(''):workspaceEmpty('No indexed documents yet. Ask SPARKLE to ingest a document from the configured documents folder.'))+
    (evidence.length?`<article class="surface"><h3>Evidence and outputs</h3>${evidence.slice(0,40).map(n=>`<div class="mini-row"><span>${esc(n.title)}<br><small class="muted">${esc(n.type)} · ${esc(n.status)}</small></span>${n.goal_id?`<button class="action" data-execution-inspect="${esc(n.goal_id)}">Inspect source</button>`:''}</div>`).join('')}</article>`:'')+workspaceRelationships(graph);
}
function workspaceAutomations(data){
  const rows=data.automations||[];
  const controls=`<article class="surface"><h3>Create an automation</h3><p class="muted">Describe the schedule and action. SPARKLE will show the proposed action for approval.</p><form id="workspace-automation-form"><label class="field"><span>Automation request</span><textarea name="request" required rows="3" placeholder="Create a daily automation at 09:00 to inspect my task deadlines."></textarea></label><button class="action" type="submit">Plan automation</button></form></article>`;
  return controls+(rows.length?rows.map(a=>workspaceCard(a.name||'Automation '+a.automation_id,a.status,`<p class="muted">${esc(a.trigger_type)} · ${esc(a.verification_state)}${a.next_run_at?` · Next ${esc(timeText(a.next_run_at))}`:''}</p>`,a.status!=='CANCELLED'?`<button class="action" data-automation-command="${a.status==='PAUSED'?'Resume':'Pause'} automation ${Number(a.automation_id)}">${a.status==='PAUSED'?'Resume':'Pause'}</button><button class="action danger" data-automation-command="Cancel automation ${Number(a.automation_id)}">Cancel</button>`:'')).join(''):workspaceEmpty(data.available?'No automations have been created.':'Automation runtime is unavailable.'));
}
function workspaceActivity(data){
  const rows=data.events||[];
  return rows.length?rows.map(e=>workspaceCard(String(e.event_type||'Event').replaceAll('_',' '),'RECORDED',`<p class="muted">${esc(timeText(e.created_at))}</p>`,e.goal_id?`<button class="action" data-execution-inspect="${esc(e.goal_id)}">Inspect execution</button>`:'')).join(''):workspaceEmpty('No execution activity yet.');
}
function workspaceSystem(data){
  const intel=data.intelligence||{},diagnostics=intel.diagnostics||{},models=intel.capabilities?.models||[],connectors=intel.connectors?.items||[];
  return workspaceCard('System health',diagnostics.healthy?'HEALTHY':diagnostics.status||'UNAVAILABLE',`<p class="muted">Storage ${diagnostics.storage?.available?'available':'unavailable'}</p>${(diagnostics.issues||[]).map(i=>`<p>${esc(i.component)}: ${esc(i.cause||'Needs inspection')}</p>`).join('')}`)+
    `<article class="surface"><h3>Models</h3>${models.map(m=>`<div class="mini-row"><span>${esc(m.capability)}<br><small class="muted">${esc(m.model||m.reason||'No configured route')}</small></span><span class="${statusClass(m.status)}">${esc(m.status)}</span></div>`).join('')||'<p class="muted">No model state available.</p>'}</article>`+
    `<article class="surface"><h3>Connectors</h3>${connectors.map(c=>`<div class="mini-row"><span>${esc(c.name||c.connector_id)}<br><small class="muted">${esc(c.reason||c.authorization_state||'')}</small></span><span class="${statusClass(c.status)}">${esc(c.status)}</span></div>`).join('')||'<p class="muted">No connector state available.</p>'}</article>`;
}
async function loadWorkspacePage(name){
  const el=$('#workspace-'+name);if(!el)return;
  el.innerHTML=workspaceEmpty('Loading saved '+name+'…');
  try{
    const paths={execution:'/api/executions',memory:'/api/memory',knowledge:'/api/knowledge',automation:'/api/automations',activity:'/api/activity',system:'/api/system'};
    const [data,graph]=await Promise.all([api(paths[name]),name==='knowledge'?api('/api/graph'):Promise.resolve({})]);
    if(state.view&&state.view!==name)return;
    const renderers={execution:workspaceExecutions,memory:workspaceMemory,knowledge:workspaceKnowledge,automation:workspaceAutomations,activity:workspaceActivity,system:workspaceSystem};
    el.innerHTML=renderers[name](data,graph);
  }catch(error){el.innerHTML=workspaceEmpty('Unable to load '+name+': '+error.message);throw error}
}
async function inspectExecution(goalId){
  const data=await api('/api/executions/'+encodeURIComponent(goalId));
  let dialog=$('#execution-inspector');
  if(!dialog){dialog=document.createElement('dialog');dialog.id='execution-inspector';dialog.className='workspace-dialog';document.body.appendChild(dialog)}
  const goal=data.goal||{},run=data.run||{},steps=data.plan?.steps||[],criteria=data.criteria||[];
  dialog.innerHTML=`<div class="view-header"><h3>${esc(goal.normalized_objective||'Execution')}</h3><button class="action" data-execution-close>Close</button></div><p><span class="${statusClass(run.status)}">${esc(run.status)}</span> · ${Number(run.iterations||0)} actions</p><div class="stack">${steps.map(s=>workspaceCard(s.description,s.status,`<p class="muted">${esc(s.preferred_tool)} · ${Number(s.attempts)} attempts</p><p>${esc(s.result?.verification?.method||'Verification pending')}</p>`)).join('')||workspaceEmpty('No executable plan has been saved.')}<article class="surface"><h3>Success criteria</h3>${criteria.map(c=>`<p>${esc(c.description)} · ${esc(c.status)}</p>`).join('')||'<p class="muted">No verified criteria yet.</p>'}</article>${(run.recovery_history||[]).length?`<article class="surface"><h3>Recovery</h3>${run.recovery_history.map(r=>`<p>${esc(r.category)} · ${esc(r.action)} · Attempt ${Number(r.attempt)}</p>`).join('')}</article>`:''}</div>`;
  dialog.showModal();
}
document.addEventListener('click',async event=>{
  const edit=event.target.closest('[data-os-edit]');
  if(edit){editOSItem(edit.dataset.osEdit,edit.dataset.id);return}
  const inspect=event.target.closest('[data-execution-inspect]'),control=event.target.closest('[data-execution-control]'),memory=event.target.closest('[data-memory-decision]'),refresh=event.target.closest('[data-workspace-refresh]'),automation=event.target.closest('[data-automation-command]');
  if(event.target.closest('[data-execution-close]')){$('#execution-inspector').close();return}
  try{
    if(inspect)await inspectExecution(inspect.dataset.executionInspect);
    if(control){control.disabled=true;await api('/api/tasks/'+encodeURIComponent(control.dataset.goalId)+'/'+control.dataset.executionControl,{method:'POST',body:'{}'});await loadWorkspacePage('execution');}
    if(memory){memory.disabled=true;await api('/api/memory/'+encodeURIComponent(memory.dataset.id)+'/'+memory.dataset.memoryDecision,{method:'POST',body:'{}'});await loadWorkspacePage('memory');}
    if(refresh)await loadWorkspacePage(refresh.dataset.workspaceRefresh);
    if(automation)await send(automation.dataset.automationCommand);
  }catch(error){if(control)control.disabled=false;if(memory)memory.disabled=false;toast(error.message)}
});
document.addEventListener('submit',async event=>{
  if(event.target.id!=='workspace-automation-form')return;
  event.preventDefault();const input=event.target.elements.request;
  if(input?.value.trim())await send(input.value.trim()).catch(error=>toast(error.message));
});
