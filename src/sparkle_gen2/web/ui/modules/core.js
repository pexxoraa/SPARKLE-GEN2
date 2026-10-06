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
function setView(name,{load=true}={}){if(name!=='chat'&&typeof voice!=='undefined'&&voice.mode!=='idle')stopLiveVoice(true).catch(()=>{});$$('.view').forEach(v=>v.classList.toggle('active',v.id===`view-${name}`));$$('.nav-item').forEach(v=>v.classList.toggle('active',v.dataset.view===name));$$('.mobile-nav-item').forEach(v=>v.classList.toggle('active',v.dataset.view===name));const titles={home:['PERSONAL WORKSPACE','Home'],chat:['CONTINUOUS CONTEXT','Conversation'],tasks:['ORCHESTRATION','Tasks'],['device-agent']:['DEVICE EXECUTION','Device Agent'],goals:['LONG-TERM DIRECTION','Goals'],projects:['PROJECT SPACE','Projects'],learning:['LEARNING OS','Learning'],skills:['CAPABILITY GRAPH','Skills'],research:['RESEARCH LAB','Research'],progress:['LONGITUDINAL VIEW','Progress'],approvals:['HUMAN AUTHORITY','Approvals'],devices:['TRUST BOUNDARY','Devices'],notifications:['ATTENTION','Inbox'],artifacts:['VERIFIED OUTPUTS','Artifacts'],settings:['PERSONAL CORE','Settings']};state.view=name;const title=titles[name]||['PERSONAL OS',name.charAt(0).toUpperCase()+name.slice(1)];$('#view-eyebrow').textContent=title[0];$('#view-title').textContent=title[1];$('.sidebar').classList.remove('open');if(typeof loadWorkspacePage==='function'&&['knowledge','memory','execution','automation','activity','system'].includes(name))loadWorkspacePage(name).catch(e=>toast(e.message));if(name==='chat'&&load)loadMessages();if(['goals','projects','learning','skills','research','progress','settings'].includes(name))loadOS().catch(e=>toast(e.message));}
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
