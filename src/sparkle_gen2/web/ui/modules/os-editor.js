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
