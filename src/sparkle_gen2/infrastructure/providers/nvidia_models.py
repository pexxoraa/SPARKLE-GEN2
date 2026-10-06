from __future__ import annotations
import json,random,time,urllib.error,urllib.request
from typing import Any,Callable,Iterable
from sparkle.model import ModelAdapter,ModelError,ModelRequest,ModelResponse
from sparkle.secrets import SecretNotFoundError,SecretResolver


class _NoProviderRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise ModelError('Provider redirect is not permitted',retryable=False,category='security_boundary')

def _provider_opener():
    # Default HTTPSHandler validates TLS; credentials must never follow redirects.
    return urllib.request.build_opener(_NoProviderRedirect()).open

def _validated_endpoint(value,*,test_transport=False):
    from urllib.parse import urlsplit
    p=urlsplit(str(value))
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.fragment:
        raise ValueError('provider_endpoint_requires_tls')
    if not test_transport and p.hostname not in {'integrate.api.nvidia.com','ai.api.nvidia.com'}:
        raise ValueError('provider_endpoint_not_allowlisted')
    if p.port not in {None,443}:raise ValueError('provider_endpoint_port_not_allowlisted')
    return str(value)

def _read_response(response,limit=16_000_000):
    raw=response.read(limit+1)
    if not isinstance(raw,bytes) or len(raw)>limit:raise ValueError('provider_response_exceeds_limit')
    return raw


class NVIDIAEmbeddingAdapter(ModelAdapter):
    """NVIDIA NIM embeddings adapter exposed through the existing ModelRegistry factory boundary."""
    provider='nvidia'
    supported_modalities=frozenset({'text'})
    def __init__(self,config:dict[str,Any],secrets:SecretResolver,*,opener:Callable[...,Any]|None=None,sleeper:Callable[[float],None]=time.sleep):
        self._config=config;self._secrets=secrets;self._opener=opener or _provider_opener();self._sleeper=sleeper;self.model_id=str(config['model_id']);self._base_url=_validated_endpoint(config['base_url'],test_transport=opener is not None);self._secret_refs=list(config['secret_refs']);self._timeout=float(config.get('timeout_seconds',120));retry=config.get('retry',{});self._attempts=max(1,min(3,int(retry.get('attempts',3))));self._base_delay=max(0.0,float(retry.get('base_delay_seconds',.5)))
    def health(self):return {'provider':self.provider,'model':self.model_id,'configured':any(self._secrets.status(self._secret_refs).values()),'endpoint':self._base_url,'enabled':bool(self._config.get('enabled',True)),'adapter_modalities':['text'],'operation':'embeddings'}
    def _headers(self):
        try:key=self._secrets.first(self._secret_refs)
        except SecretNotFoundError:raise ModelError('NVIDIA credential is not configured',retryable=False,category='configuration_failure') from None
        return {'Authorization':f'Bearer {key}','Content-Type':'application/json','Accept':'application/json','User-Agent':'SPARKLE/0.30'}
    @staticmethod
    def _error(status):
        return ModelError('NVIDIA embedding authentication failed; verify the configured server-side key' if status in {401,403} else 'NVIDIA embedding request failed',retryable=status in {408,409,429,500,502,503,504},status_code=status,category={401:'authentication_failure',403:'authentication_failure',404:'model_unavailable',408:'timeout',429:'rate_limited'}.get(status,'provider_failure'))
    def embed(self,texts:str|Iterable[str],*,input_type='query')->list[list[float]]:
        values=[texts] if isinstance(texts,str) else list(texts)
        if not values or len(values)>128 or any(not isinstance(x,str) or not x.strip() or len(x.encode('utf-8'))>1_000_000 for x in values):raise ValueError('embedding input must contain 1..128 bounded non-empty text values')
        if sum(len(x.encode('utf-8')) for x in values)>1_000_000:raise ValueError('embedding total input exceeds limit')
        if input_type not in {'query','passage'}:raise ValueError('embedding input_type must be query or passage')
        payload={'input':values,'model':self.model_id,'input_type':input_type};body=json.dumps(payload,separators=(',',':')).encode();last=None
        for attempt in range(self._attempts):
            req=urllib.request.Request(self._base_url,data=body,headers=self._headers(),method='POST')
            try:
                with self._opener(req,timeout=self._timeout) as response:raw=_read_response(response)
                data=json.loads(raw.decode());rows=data.get('data') if isinstance(data,dict) else None
                if not isinstance(rows,list) or len(rows)!=len(values):raise TypeError('embedding response data mismatch')
                indices=[r.get('index') for r in rows if isinstance(r,dict)]
                if len(indices)!=len(values) or any(isinstance(i,bool) or not isinstance(i,int) for i in indices) or set(indices)!=set(range(len(values))):raise TypeError('embedding indices invalid')
                ordered=sorted(rows,key=lambda r:r['index']);vectors=[]
                for row in ordered:
                    vector=row.get('embedding') if isinstance(row,dict) else None
                    if not isinstance(vector,list) or not vector or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not __import__('math').isfinite(float(x)) for x in vector):raise TypeError('embedding vector invalid')
                    vectors.append([float(x) for x in vector])
                dims={len(v) for v in vectors}
                if len(dims)!=1:raise TypeError('embedding dimensions mismatch')
                return vectors
            except urllib.error.HTTPError as exc:last=self._error(exc.code)
            except TimeoutError:last=ModelError('NVIDIA embedding request timed out',retryable=True,category='timeout')
            except urllib.error.URLError as exc:last=ModelError('NVIDIA embedding network request failed',retryable=True,category='timeout' if isinstance(exc.reason,TimeoutError) else 'connectivity_failure')
            except (ValueError,UnicodeDecodeError,TypeError,KeyError):last=ModelError('NVIDIA returned an invalid embedding response',retryable=False,category='malformed_response')
            if not last.retryable or attempt+1>=self._attempts:raise last
            delay=self._base_delay*(2**attempt)+random.uniform(0,self._base_delay/4 if self._base_delay else 0);self._sleeper(delay)
        raise last or ModelError('NVIDIA embedding request failed')
    def complete(self,request:ModelRequest)->ModelResponse:
        raise ModelError('Embedding model does not implement chat completion',retryable=False,category='unsupported_operation')

class NVIDIARerankingAdapter(ModelAdapter):
    """NVIDIA NIM ranking adapter. Returns a complete validated permutation of candidates."""
    provider='nvidia'
    supported_modalities=frozenset({'text'})
    def __init__(self,config:dict[str,Any],secrets:SecretResolver,*,opener:Callable[...,Any]|None=None,sleeper:Callable[[float],None]=time.sleep):
        self._config=config;self._secrets=secrets;self._opener=opener or _provider_opener();self._sleeper=sleeper;self.model_id=str(config['model_id']);self._base_url=_validated_endpoint(config['base_url'],test_transport=opener is not None);self._secret_refs=list(config['secret_refs']);self._timeout=float(config.get('timeout_seconds',120));self.max_candidates=max(1,min(int(config.get('max_candidates',64)),128));retry=config.get('retry',{});self._attempts=max(1,min(3,int(retry.get('attempts',3))));self._base_delay=max(0.0,float(retry.get('base_delay_seconds',.5)))
    def health(self):return {'provider':self.provider,'model':self.model_id,'configured':any(self._secrets.status(self._secret_refs).values()),'endpoint':self._base_url,'enabled':bool(self._config.get('enabled',True)),'adapter_modalities':['text'],'operation':'ranking','max_candidates':self.max_candidates}
    def _headers(self):
        try:key=self._secrets.first(self._secret_refs)
        except SecretNotFoundError:raise ModelError('NVIDIA credential is not configured',retryable=False,category='configuration_failure') from None
        return {'Authorization':f'Bearer {key}','Content-Type':'application/json','Accept':'application/json','User-Agent':'SPARKLE/0.30'}
    @staticmethod
    def _error(status):
        return ModelError('NVIDIA reranking authentication failed; verify the configured server-side key' if status in {401,403} else 'NVIDIA reranking request failed',retryable=status in {408,409,429,500,502,503,504},status_code=status,category={401:'authentication_failure',403:'authentication_failure',404:'model_unavailable',408:'timeout',429:'rate_limited'}.get(status,'provider_failure'))
    @staticmethod
    def _validated_rankings(data:Any,count:int):
        import math
        rows=data.get('rankings') if isinstance(data,dict) else None
        if not isinstance(rows,list) or len(rows)!=count:raise TypeError('ranking response count mismatch')
        seen=set();out=[]
        for row in rows:
            if not isinstance(row,dict) or 'index' not in row or 'logit' not in row:raise TypeError('ranking entry missing index/logit')
            idx=row['index'];logit=row['logit']
            if isinstance(idx,bool) or not isinstance(idx,int) or idx<0 or idx>=count or idx in seen:raise TypeError('ranking index invalid')
            if isinstance(logit,bool) or not isinstance(logit,(int,float)) or not math.isfinite(float(logit)):raise TypeError('ranking logit invalid')
            seen.add(idx);out.append({'index':idx,'logit':float(logit)})
        if seen!=set(range(count)):raise TypeError('ranking indices incomplete')
        return sorted(out,key=lambda x:(-x['logit'],x['index']))
    def rerank(self,query:str,passages:Iterable[str])->list[dict[str,Any]]:
        values=list(passages)
        if not isinstance(query,str) or not query.strip() or len(query.encode('utf-8'))>100_000:raise ValueError('reranking query must be bounded non-empty text')
        if not values or len(values)>self.max_candidates or any(not isinstance(x,str) or not x.strip() or len(x.encode('utf-8'))>100_000 for x in values):raise ValueError(f'reranking passages must contain 1..{self.max_candidates} bounded non-empty text values')
        payload={'model':self.model_id,'query':{'text':query},'passages':[{'text':x} for x in values]}
        if self._config.get('truncate') in {'NONE','START','END'}:payload['truncate']=self._config['truncate']
        body=json.dumps(payload,separators=(',',':')).encode();last=None
        for attempt in range(self._attempts):
            req=urllib.request.Request(self._base_url,data=body,headers=self._headers(),method='POST')
            try:
                with self._opener(req,timeout=self._timeout) as response:raw=_read_response(response)
                data=json.loads(raw.decode());return self._validated_rankings(data,len(values))
            except urllib.error.HTTPError as exc:last=self._error(exc.code)
            except TimeoutError:last=ModelError('NVIDIA reranking request timed out',retryable=True,category='timeout')
            except urllib.error.URLError as exc:last=ModelError('NVIDIA reranking network request failed',retryable=True,category='timeout' if isinstance(exc.reason,TimeoutError) else 'connectivity_failure')
            except (ValueError,UnicodeDecodeError,TypeError,KeyError):last=ModelError('NVIDIA returned an invalid reranking response',retryable=False,category='malformed_response')
            if not last.retryable or attempt+1>=self._attempts:raise last
            delay=self._base_delay*(2**attempt)+random.uniform(0,self._base_delay/4 if self._base_delay else 0);self._sleeper(delay)
        raise last or ModelError('NVIDIA reranking request failed')
    def complete(self,request:ModelRequest)->ModelResponse:raise ModelError('Reranking model does not implement chat completion',retryable=False,category='unsupported_operation')

class NVIDIAContentSafetyAdapter(ModelAdapter):
    """NVIDIA advisory content-safety adapter. It classifies content; it never authorizes actions."""
    provider='nvidia'
    supported_modalities=frozenset({'text'})
    def __init__(self,config:dict[str,Any],secrets:SecretResolver,*,opener:Callable[...,Any]|None=None,sleeper:Callable[[float],None]=time.sleep):
        self._config=config;self._secrets=secrets;self._opener=opener or _provider_opener();self._sleeper=sleeper;self.model_id=str(config['model_id']);self._base_url=_validated_endpoint(config['base_url'],test_transport=opener is not None);self._secret_refs=list(config['secret_refs']);self._timeout=float(config.get('timeout_seconds',120));retry=config.get('retry',{});self._attempts=max(1,min(3,int(retry.get('attempts',3))));self._base_delay=max(0.0,float(retry.get('base_delay_seconds',.5)))
    def health(self):return {'provider':self.provider,'model':self.model_id,'configured':any(self._secrets.status(self._secret_refs).values()),'endpoint':self._base_url,'enabled':bool(self._config.get('enabled',True)),'adapter_modalities':['text'],'operation':'advisory_safety'}
    def _headers(self):
        try:key=self._secrets.first(self._secret_refs)
        except SecretNotFoundError:raise ModelError('NVIDIA credential is not configured',retryable=False,category='configuration_failure') from None
        return {'Authorization':f'Bearer {key}','Content-Type':'application/json','Accept':'application/json','User-Agent':'SPARKLE/0.30'}
    @staticmethod
    def _error(status):
        return ModelError('NVIDIA content-safety authentication failed; verify the configured server-side key' if status in {401,403} else 'NVIDIA content-safety request failed',retryable=status in {408,409,429,500,502,503,504},status_code=status,category={401:'authentication_failure',403:'authentication_failure',404:'model_unavailable',408:'timeout',429:'rate_limited'}.get(status,'provider_failure'))
    @staticmethod
    def _normalize_content(content:Any)->dict[str,Any]:
        import re
        if not isinstance(content,str) or not content.strip():raise TypeError('content-safety response content missing')
        text=content.strip();parsed=None
        try:parsed=json.loads(text)
        except json.JSONDecodeError:pass
        if isinstance(parsed,dict):
            raw_label=parsed.get('label',parsed.get('classification'))
            if isinstance(parsed.get('safe'),bool):label='safe' if parsed['safe'] else 'unsafe'
            elif isinstance(raw_label,str) and raw_label.strip().lower() in {'safe','unsafe','flagged'}:label=raw_label.strip().lower()
            elif isinstance(parsed.get('violations'),list):label='safe' if not parsed['violations'] else 'flagged'
            else:raise TypeError('content-safety JSON lacks explicit advisory label')
            return {'label':label,'flagged':label in {'unsafe','flagged'},'details':parsed}
        match=re.match(r'^\s*(?:user\s+safety\s*:\s*)?(safe|unsafe|flagged)\b',text,re.IGNORECASE)
        if not match:raise TypeError('content-safety text lacks explicit advisory label')
        label=match.group(1).lower();return {'label':label,'flagged':label in {'unsafe','flagged'},'details':{'provider_text':text[:1000]}}
    def assess(self,text:str)->dict[str,Any]:
        if not isinstance(text,str) or not text.strip() or len(text.encode('utf-8'))>1_000_000:raise ValueError('safety content must be bounded non-empty text')
        payload={'model':self.model_id,'messages':[{'role':'user','content':text}],'temperature':0.0,'max_tokens':512,'stream':False};body=json.dumps(payload,separators=(',',':')).encode();last=None
        for attempt in range(self._attempts):
            req=urllib.request.Request(self._base_url,data=body,headers=self._headers(),method='POST')
            try:
                with self._opener(req,timeout=self._timeout) as response:raw=_read_response(response)
                data=json.loads(raw.decode());choices=data.get('choices') if isinstance(data,dict) else None
                if not isinstance(choices,list) or not choices or not isinstance(choices[0],dict) or not isinstance(choices[0].get('message'),dict):raise TypeError('content-safety response choices missing')
                result=self._normalize_content(choices[0]['message'].get('content'));result['provider_request_id']=str(data.get('id')) if data.get('id') else None;return result
            except urllib.error.HTTPError as exc:last=self._error(exc.code)
            except TimeoutError:last=ModelError('NVIDIA content-safety request timed out',retryable=True,category='timeout')
            except urllib.error.URLError as exc:last=ModelError('NVIDIA content-safety network request failed',retryable=True,category='timeout' if isinstance(exc.reason,TimeoutError) else 'connectivity_failure')
            except (ValueError,UnicodeDecodeError,TypeError,KeyError):last=ModelError('NVIDIA returned an invalid content-safety response',retryable=False,category='malformed_response')
            if not last.retryable or attempt+1>=self._attempts:raise last
            delay=self._base_delay*(2**attempt)+random.uniform(0,self._base_delay/4 if self._base_delay else 0);self._sleeper(delay)
        raise last or ModelError('NVIDIA content-safety request failed')
    def complete(self,request:ModelRequest)->ModelResponse:raise ModelError('Content-safety model exposes advisory assessment, not general chat completion',retryable=False,category='unsupported_operation')


class NVIDIAVoiceChatAdapter(ModelAdapter):
    """NVIDIA Nemotron VoiceChat adapter contract.

    The hosted NVCF streaming transport is intentionally gated until an
    intermediary/protocol endpoint has been independently verified. Tests may
    inject a transport object; production configuration never guesses a URL.
    """
    provider='nvidia'
    supported_modalities=frozenset({'text','audio'})
    def __init__(self,config:dict[str,Any],secrets:SecretResolver,*,transport=None):
        self._config=dict(config);self._secrets=secrets;self.model_id=str(config['model_id']);self._secret_refs=list(config.get('secret_refs',[]));self.function_id=str(config.get('function_id',''));self.function_version=str(config.get('function_version',''));self.transport_verified=bool(config.get('transport_verified',False) or transport is not None)
        self._transport=transport
        if self._transport is None and self.transport_verified:
            from .nvidia_voicechat_transport import NVIDIAHostedVoiceChatTransport
            self._transport=NVIDIAHostedVoiceChatTransport(function_id=self.function_id,secrets=secrets,secret_refs=self._secret_refs,websocket_url=config.get('websocket_url'))
    def health(self):
        secret_status=self._secrets.status(self._secret_refs)
        return {'provider':self.provider,'model':self.model_id,'configured':bool(self._secret_refs) and all(secret_status.values()),'enabled':bool(self._config.get('enabled',True)),'adapter_modalities':['text','audio'],'operation':'realtime_voicechat','supports_streaming':True,'transport_verified':self.transport_verified,'transport_kind':self._config.get('transport_kind'),'hosted_endpoint_configured':bool(self._config.get('websocket_url')),'function_id':self.function_id or None,'function_version':self.function_version or None,'health_path':self._config.get('health_path')}
    def _require_transport(self):
        if self._transport is None or not self.transport_verified:raise ModelError('NVIDIA VoiceChat streaming transport is not verified/configured; direct endpoint guessing is prohibited',retryable=False,category='external_dependency')
        return self._transport
    def open_session(self,session):return self._require_transport().open_session(session)
    def send_audio(self,provider_session_reference,frame):return self._require_transport().send_audio(provider_session_reference,frame)
    def respond_text(self,provider_session_reference,text):return self._require_transport().respond_text(provider_session_reference,text)
    def interrupt(self,provider_session_reference):
        fn=getattr(self._require_transport(),'interrupt',None);return fn(provider_session_reference) if callable(fn) else {'interrupted':False}
    def close_session(self,provider_session_reference):
        fn=getattr(self._require_transport(),'close_session',None);return fn(provider_session_reference) if callable(fn) else {'closed':True}
    def complete(self,request:ModelRequest)->ModelResponse:raise ModelError('VoiceChat uses the realtime voice session operation, not chat completion',retryable=False,category='unsupported_operation')


class NVIDIAImageGenerationAdapter(ModelAdapter):
    """NVIDIA FLUX image-generation adapter over the existing ModelRegistry boundary."""
    provider='nvidia'
    supported_modalities=frozenset({'text'})
    MAX_PROMPT_BYTES=16000;MAX_DECODED_BYTES=10_000_000
    def __init__(self,config:dict[str,Any],secrets:SecretResolver,*,opener:Callable[...,Any]|None=None,sleeper:Callable[[float],None]=time.sleep):
        self._config=dict(config);self._secrets=secrets;self._opener=opener or _provider_opener();self._sleeper=sleeper;self.model_id=str(config['model_id']);self._base_url=_validated_endpoint(config['base_url'],test_transport=opener is not None);self._secret_refs=list(config['secret_refs']);self._timeout=float(config.get('timeout_seconds',180));retry=config.get('retry',{});self._attempts=max(1,min(3,int(retry.get('attempts',2))));self._base_delay=max(0.0,float(retry.get('base_delay_seconds',1.0)))
    def health(self):return {'provider':self.provider,'model':self.model_id,'configured':any(self._secrets.status(self._secret_refs).values()),'endpoint':self._base_url,'enabled':bool(self._config.get('enabled',True)),'adapter_modalities':['text'],'operation':'image_generation'}
    def _headers(self):
        try:key=self._secrets.first(self._secret_refs)
        except SecretNotFoundError:raise ModelError('NVIDIA credential is not configured',retryable=False,category='configuration_failure') from None
        return {'Authorization':f'Bearer {key}','Content-Type':'application/json','Accept':'application/json','User-Agent':'SPARKLE/0.30'}
    @staticmethod
    def _validate(prompt,height,width,samples,seed,steps):
        if not isinstance(prompt,str) or not prompt.strip() or len(prompt.encode('utf-8'))>NVIDIAImageGenerationAdapter.MAX_PROMPT_BYTES:raise ValueError('image prompt must be bounded non-empty text')
        for name,value in (('height',height),('width',width)):
            if isinstance(value,bool) or not isinstance(value,int) or value<256 or value>2048 or value%8:raise ValueError(f'image {name} must be an integer 256..2048 divisible by 8')
        if height*width>4_194_304:raise ValueError('image dimensions exceed pixel budget')
        if samples!=1:raise ValueError('image samples must equal 1 for the verified provider contract')
        if isinstance(seed,bool) or not isinstance(seed,int) or not 0<=seed<=4_294_967_295:raise ValueError('image seed must be uint32')
        if isinstance(steps,bool) or not isinstance(steps,int) or not 1<=steps<=50:raise ValueError('image steps must be 1..50')
    @staticmethod
    def _error(status):
        return ModelError('NVIDIA image-generation authentication failed; verify the configured server-side key' if status in {401,403} else 'NVIDIA image-generation request failed',retryable=status in {408,409,429,500,502,503,504},status_code=status,category={401:'authentication_failure',403:'authentication_failure',404:'model_unavailable',408:'timeout',429:'rate_limited'}.get(status,'provider_failure'))
    def generate_image(self,prompt:str,*,height=1024,width=1024,samples=1,seed=1,steps=4):
        import base64,math
        self._validate(prompt,height,width,samples,seed,steps);payload={'prompt':prompt,'height':height,'width':width,'samples':samples,'seed':seed,'steps':steps};body=json.dumps(payload,separators=(',',':')).encode();last=None
        for attempt in range(self._attempts):
            req=urllib.request.Request(self._base_url,data=body,headers=self._headers(),method='POST')
            try:
                with self._opener(req,timeout=self._timeout) as response:
                    raw=_read_response(response);headers=getattr(response,'headers',{})
                data=json.loads(raw.decode());artifacts=data.get('artifacts') if isinstance(data,dict) else None
                if not isinstance(artifacts,list) or len(artifacts)!=1 or not isinstance(artifacts[0],dict):raise TypeError('image artifacts response invalid')
                art=artifacts[0];encoded=art.get('base64')
                if not isinstance(encoded,str) or not encoded:raise TypeError('image artifact base64 missing')
                if len(encoded)>((self.MAX_DECODED_BYTES+2)//3)*4+8:raise TypeError('image artifact encoded size invalid')
                try:decoded=base64.b64decode(encoded,validate=True)
                except Exception as exc:raise TypeError('image artifact base64 invalid') from exc
                if not decoded or len(decoded)>self.MAX_DECODED_BYTES:raise TypeError('image artifact byte size invalid')
                if not (decoded.startswith(b'\x89PNG\r\n\x1a\n') or decoded.startswith(b'\xff\xd8')):raise TypeError('image artifact format invalid')
                returned_seed=art.get('seed',seed)
                if isinstance(returned_seed,bool) or not isinstance(returned_seed,(int,float)) or not math.isfinite(float(returned_seed)) or int(returned_seed)!=float(returned_seed):raise TypeError('image artifact seed invalid')
                finish=art.get('finishReason')
                if finish is not None and not isinstance(finish,str):raise TypeError('image finishReason invalid')
                def hget(name):
                    try:return headers.get(name)
                    except Exception:return None
                provider_status=hget('Nvcf-Status') or hget('NVCF-STATUS')
                if provider_status is not None and str(provider_status).strip().lower()!='fulfilled':raise TypeError('NVIDIA image-generation status is not fulfilled')
                return {'image_bytes':decoded,'seed':int(returned_seed),'finish_reason':finish,'provider_request_id':hget('Nvcf-Reqid') or hget('NVCF-REQID'),'provider_status':provider_status}
            except urllib.error.HTTPError as exc:last=self._error(exc.code)
            except TimeoutError:last=ModelError('NVIDIA image-generation request timed out',retryable=True,category='timeout')
            except urllib.error.URLError as exc:last=ModelError('NVIDIA image-generation network request failed',retryable=True,category='timeout' if isinstance(exc.reason,TimeoutError) else 'connectivity_failure')
            except (ValueError,UnicodeDecodeError,TypeError,KeyError,json.JSONDecodeError):last=ModelError('NVIDIA returned an invalid image-generation response',retryable=False,category='malformed_response')
            if not last.retryable or attempt+1>=self._attempts:raise last
            self._sleeper(self._base_delay*(2**attempt))
        raise last or ModelError('NVIDIA image-generation request failed')
    def complete(self,request:ModelRequest)->ModelResponse:raise ModelError('Image-generation model does not implement chat completion',retryable=False,category='unsupported_operation')
