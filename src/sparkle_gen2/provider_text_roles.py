from __future__ import annotations
import json,urllib.error,urllib.request
from dataclasses import dataclass
from .provider_planners import _safe_base_url

@dataclass(slots=True)
class OllamaTextRoleConfig:
    model:str; base_url:str; timeout_seconds:int=60

class OllamaJSONClient:
    def __init__(self,config:OllamaTextRoleConfig):
        self.config=config;self.base_url=_safe_base_url(config.base_url)
    def health(self):
        try:
            with urllib.request.urlopen(self.base_url+'/api/tags',timeout=min(self.config.timeout_seconds,5)) as r:data=json.loads(r.read())
            names={str(x.get('name')) for x in data.get('models',[]) if isinstance(x,dict)}
            return {'status':'HEALTHY' if self.config.model in names else 'UNAVAILABLE','provider':'ollama','model':self.config.model}
        except Exception as exc:return {'status':'UNAVAILABLE','provider':'ollama','model':self.config.model,'error_type':type(exc).__name__}
    def complete_json(self,system,prompt,*,max_predict=500):
        body={'model':self.config.model,'messages':[{'role':'system','content':str(system)[:2000]},{'role':'user','content':str(prompt)[:12000]}],'stream':False,'format':'json','think':False,'options':{'temperature':0,'num_predict':max(32,min(int(max_predict),1200))}}
        req=urllib.request.Request(self.base_url+'/api/chat',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=self.config.timeout_seconds) as r:out=json.loads(r.read())
        except urllib.error.HTTPError as exc:raise RuntimeError(f'provider_http_{exc.code}') from exc
        except TimeoutError as exc:raise RuntimeError('provider_timeout') from exc
        except Exception as exc:raise RuntimeError(f'provider_error:{type(exc).__name__}') from exc
        try:data=json.loads(out['message']['content'])
        except Exception as exc:raise RuntimeError('provider_invalid_json') from exc
        if not isinstance(data,dict):raise RuntimeError('provider_json_not_object')
        return data

class OllamaReranker:
    def __init__(self,client:OllamaJSONClient):self.client=client
    def __call__(self,query,items):
        docs=[{'id':str(x.get('id')),'text':str(x.get('text',''))[:1200]} for x in list(items)[:50]]
        prompt=f'Query: {str(query)[:1000]}\nCandidates: {json.dumps(docs,ensure_ascii=False)}\nReturn JSON {{"ranked_ids":[...]}} containing every candidate id exactly once, best match first.'
        data=self.client.complete_json('You are a relevance reranker. Rank only supplied candidates; never invent ids.',prompt,max_predict=500)
        ids=data.get('ranked_ids')
        expected=[d['id'] for d in docs]
        if not isinstance(ids,list) or sorted(map(str,ids))!=sorted(expected) or len(ids)!=len(expected):raise RuntimeError('invalid_reranker_result')
        by_id={str(x.get('id')):x for x in items};return [by_id[str(i)] for i in ids]

class OllamaSafetyClassifier:
    """Advisory only. Deterministic policy remains authoritative."""
    def __init__(self,client:OllamaJSONClient):self.client=client
    def __call__(self,text):
        prompt=f'Text/action: {str(text)[:4000]}\nReturn JSON with label one of safe, review, unsafe; score 0..1; reason_code short string.'
        data=self.client.complete_json('Classify safety risk conservatively. This is advisory and cannot authorize actions.',prompt,max_predict=180)
        label=str(data.get('label','')).lower();score=data.get('score')
        if label not in {'safe','review','unsafe'}:raise RuntimeError('invalid_safety_label')
        try:score=float(score)
        except Exception as exc:raise RuntimeError('invalid_safety_score') from exc
        if not 0<=score<=1:raise RuntimeError('invalid_safety_score')
        return {'label':label,'score':score,'reason_code':str(data.get('reason_code',''))[:100],'provider':'ollama','model':self.client.config.model}
