/* SPARKLE UI bootstrap. Runtime code is split by responsibility under /ui/modules/. */
(function(){
  const modules=['core.js','os.js','conversation.js','voice.js','os-editor.js','interactions.js','bootstrap.js'];
  let chain=Promise.resolve();
  for(const name of modules){
    chain=chain.then(()=>new Promise((resolve,reject)=>{
      const script=document.createElement('script');
      script.src='/ui/modules/'+name+'?v=21';
      script.onload=resolve;
      script.onerror=()=>reject(new Error('Failed to load UI module: '+name));
      document.head.appendChild(script);
    }));
  }
  chain.catch(error=>console.error('[SPARKLE] UI bootstrap failed',error));
})();
