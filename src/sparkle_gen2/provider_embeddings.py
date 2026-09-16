from __future__ import annotations
import json,math,urllib.error,urllib.request
from dataclasses import dataclass
from .provider_planners import _safe_base_url

@dataclass(slots=True)
class OllamaEmbeddingConfig:
    model:str; base_url:str; timeout_seconds:int=30

class OllamaEmbedder:
    """Bounded Ollama embedding transport behind the retrieval callable contract."""
    def __init__(self,config:OllamaEmbeddingConfig):
        self.config=config;self.base_url=_safe_base_url(config.base_url)
    def health(self):
        try:
            with urllib.request.urlopen(self.base_url+'/api/tags',timeout=min(self.config.timeout_seconds,5)) as r:data=json.loads(r.read())
            names={str(x.get('name')) for x in data.get('models',[]) if isinstance(x,dict)}
            return {'status':'HEALTHY' if self.config.model in names else 'UNAVAILABLE','provider':'ollama','model':self.config.model}
        except Exception as exc:return {'status':'UNAVAILABLE','provider':'ollama','model':self.config.model,'error_type':type(exc).__name__}
    def __call__(self,text):
        if not isinstance(text,str) or not text.strip():raise ValueError('embedding_text_required')
        body={'model':self.config.model,'input':text[:12000]}
        req=urllib.request.Request(self.base_url+'/api/embed',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=self.config.timeout_seconds) as r:out=json.loads(r.read())
        except urllib.error.HTTPError as exc:raise RuntimeError(f'provider_http_{exc.code}') from exc
        except TimeoutError as exc:raise RuntimeError('provider_timeout') from exc
        except Exception as exc:raise RuntimeError(f'provider_error:{type(exc).__name__}') from exc
        vectors=out.get('embeddings')
        if not isinstance(vectors,list) or len(vectors)!=1 or not isinstance(vectors[0],list) or not vectors[0]:raise RuntimeError('invalid_embedding_result')
        vector=[]
        for value in vectors[0]:
            try:number=float(value)
            except Exception as exc:raise RuntimeError('invalid_embedding_value') from exc
            if not math.isfinite(number):raise RuntimeError('invalid_embedding_value')
            vector.append(number)
        if len(vector)>8192:raise RuntimeError('embedding_dimension_exceeds_bound')
        return vector
