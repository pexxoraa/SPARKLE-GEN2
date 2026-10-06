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
