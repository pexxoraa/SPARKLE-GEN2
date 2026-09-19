from __future__ import annotations
import hashlib,json,os,struct,uuid
from dataclasses import asdict,dataclass,field
from pathlib import Path,PurePosixPath
from typing import Any
from .core_time import now

BLOCKED_EXTERNAL_CLASSIFICATIONS=frozenset({'SENSITIVE','HIGHLY_SENSITIVE','DEVICE_CONTROL'})
MAX_IMAGE_BYTES=10_000_000

@dataclass(frozen=True,slots=True)
class ImageGenerationRequest:
    request_id:str;owner_user_id:str;prompt:str;height:int=1024;width:int=1024;samples:int=1;seed:int=1;steps:int=4;classification:str='PRIVATE';goal_id:str|None=None;task_run_id:str|None=None;trace_id:str|None=None;step_id:str|None=None
    def provider_args(self):return {'prompt':self.prompt,'height':self.height,'width':self.width,'samples':self.samples,'seed':self.seed,'steps':self.steps}
    def safe_provenance(self):return {'request_id':self.request_id,'owner_user_id':self.owner_user_id,'prompt_sha256':hashlib.sha256(self.prompt.encode()).hexdigest(),'height':self.height,'width':self.width,'samples':self.samples,'seed':self.seed,'steps':self.steps,'classification':self.classification,'goal_id':self.goal_id,'task_run_id':self.task_run_id,'trace_id':self.trace_id,'step_id':self.step_id}

@dataclass(frozen=True,slots=True)
class GeneratedImageInfo:
    media_type:str;width:int;height:int;byte_count:int;sha256:str
    def to_dict(self):return asdict(self)

@dataclass(slots=True)
class ImageGenerationResult:
    request_id:str;status:str;artifact_id:int|None;artifact_name:str|None;artifact_sha256:str|None;media_type:str|None;width:int|None;height:int|None;provider:str|None;model:str|None;fallback:bool;provider_request_id:str|None;provider_status:str|None;attempt:int;reused:bool;verification:dict[str,Any]=field(default_factory=dict);provenance:dict[str,Any]=field(default_factory=dict)
    def to_dict(self):return asdict(self)

def inspect_image_bytes(data:bytes)->GeneratedImageInfo:
    if not isinstance(data,(bytes,bytearray)) or not data or len(data)>MAX_IMAGE_BYTES:raise ValueError('generated image byte size invalid')
    raw=bytes(data);width=height=0;media=None
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        if len(raw)<33:raise ValueError('PNG image is truncated')
        pos=8;seen_ihdr=False;seen_idat=False;seen_iend=False
        while pos+12<=len(raw):
            length=int.from_bytes(raw[pos:pos+4],'big');kind=raw[pos+4:pos+8];end=pos+12+length
            if length<0 or end>len(raw):raise ValueError('PNG chunk length invalid')
            payload=raw[pos+8:pos+8+length]
            if kind==b'IHDR':
                if seen_ihdr or length!=13:raise ValueError('PNG IHDR invalid')
                width=int.from_bytes(payload[:4],'big');height=int.from_bytes(payload[4:8],'big');seen_ihdr=True
            elif kind==b'IDAT' and length>0:seen_idat=True
            elif kind==b'IEND':
                if length!=0:raise ValueError('PNG IEND invalid')
                seen_iend=True;break
            pos=end
        if not (seen_ihdr and seen_idat and seen_iend) or width<1 or height<1:raise ValueError('PNG image structure invalid')
        media='image/png'
    elif raw.startswith(b'\xff\xd8'):
        if len(raw)<64 or not raw.endswith(b'\xff\xd9'):raise ValueError('JPEG image is truncated')
        pos=2;sof={0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF};seen_sof=False;scan_payload=False
        while pos<len(raw)-1:
            if raw[pos]!=0xFF:pos+=1;continue
            while pos<len(raw) and raw[pos]==0xFF:pos+=1
            if pos>=len(raw):break
            marker=raw[pos];pos+=1
            if marker in {0xD8,0xD9,0x01} or 0xD0<=marker<=0xD7:continue
            if pos+2>len(raw):raise ValueError('JPEG segment truncated')
            length=int.from_bytes(raw[pos:pos+2],'big')
            if length<2 or pos+length>len(raw):raise ValueError('JPEG segment length invalid')
            if marker in sof:
                if length<7:raise ValueError('JPEG SOF invalid')
                height=int.from_bytes(raw[pos+3:pos+5],'big');width=int.from_bytes(raw[pos+5:pos+7],'big');seen_sof=True
            if marker==0xDA:
                data_start=pos+length
                scan_payload=data_start<len(raw)-2
                break
            pos+=length
        if not seen_sof or width<1 or height<1 or not scan_payload:raise ValueError('JPEG image structure invalid')
        media='image/jpeg'
    else:raise ValueError('unsupported generated image format')
    return GeneratedImageInfo(media,width,height,len(raw),hashlib.sha256(raw).hexdigest())

class ImageGenerationService:
    """Capability-routed image generation using the existing authoritative artifact registry."""
    PROJECT='generated_images'
    def __init__(self,store,model_manager,gen1_gateway):self.store=store;self.model_manager=model_manager;self.gen1=gen1_gateway
    @staticmethod
    def _canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    @classmethod
    def identity(cls,*,owner_user_id,prompt,height,width,samples,seed,steps,classification,goal_id,task_run_id,step_id):
        value={'owner_user_id':owner_user_id,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'height':height,'width':width,'samples':samples,'seed':seed,'steps':steps,'classification':classification,'goal_id':goal_id,'task_run_id':task_run_id,'step_id':step_id};digest=hashlib.sha256(cls._canonical(value).encode()).hexdigest();return 'imgreq_'+digest[:32],digest
    def _manager(self):
        manager=getattr(getattr(self.gen1,'system',None),'artifacts',None)
        if manager is None:raise RuntimeError('authoritative_artifact_manager_unavailable')
        return manager
    def _artifact_by_source(self,digest):
        manager=self._manager()
        with manager.connect() as db:row=db.execute('SELECT * FROM artifacts WHERE project_name=? AND source_digest=?',(self.PROJECT,digest)).fetchone()
        if row is None:return None
        return {'artifact_id':row['id'],'project_name':row['project_name'],'source_digest':row['source_digest'],'artifact_name':row['artifact_name'],'artifact_sha256':row['artifact_sha256'],'manifest':json.loads(row['manifest_json']),'file_count':row['file_count'],'source_bytes':row['source_bytes'],'artifact_bytes':row['artifact_bytes'],'status':row['status'],'created_at':row['created_at']}
    def _persist_artifact(self,request,digest,image,info,provider):
        manager=self._manager();ext='.jpg' if info.media_type=='image/jpeg' else '.png';artifact_name=f'{self.PROJECT}/{digest[:32]}{ext}';root=manager.artifact_root.resolve();target=(root.joinpath(*PurePosixPath(artifact_name).parts)).resolve()
        if root not in target.parents or root.is_symlink():raise RuntimeError('artifact_path_invalid')
        target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if target.parent.is_symlink():raise RuntimeError('artifact_path_invalid')
        reused=target.exists()
        if reused:
            if target.is_symlink() or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=info.sha256:raise RuntimeError('existing image artifact failed integrity validation')
        else:
            try:
                fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_CLOEXEC',0)|getattr(os,'O_NOFOLLOW',0),0o600)
                with os.fdopen(fd,'wb') as handle:handle.write(image);handle.flush();os.fsync(handle.fileno())
            except Exception:
                target.unlink(missing_ok=True);raise
        manifest={'artifact_kind':'image_generation','request_id':request.request_id,'prompt_sha256':request.safe_provenance()['prompt_sha256'],'provider':provider['provider'],'model':provider['model'],'capability':'image_generation','fallback':bool(provider['fallback']),'provider_request_id':provider.get('provider_request_id'),'provider_status':provider.get('provider_status'),'generation':{'height':request.height,'width':request.width,'samples':request.samples,'seed':request.seed,'steps':request.steps},'media_type':info.media_type,'width':info.width,'height':info.height,'artifact_sha256':info.sha256,'owner_user_id':request.owner_user_id,'goal_id':request.goal_id,'task_run_id':request.task_run_id,'trace_id':request.trace_id,'step_id':request.step_id,'classification':request.classification}
        created=now()
        with manager.connect() as db:
            db.execute('INSERT INTO artifacts(project_name,source_digest,artifact_name,artifact_sha256,manifest_json,file_count,source_bytes,artifact_bytes,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(project_name,source_digest) DO NOTHING',(self.PROJECT,digest,artifact_name,info.sha256,self._canonical(manifest),1,len(request.prompt.encode()),len(image),'generated_verified',created))
            row=db.execute('SELECT * FROM artifacts WHERE project_name=? AND source_digest=?',(self.PROJECT,digest)).fetchone()
        if row is None or row['artifact_name']!=artifact_name or row['artifact_sha256']!=info.sha256:raise RuntimeError('image artifact record failed immutable consistency validation')
        return {'artifact_id':row['id'],'artifact_name':row['artifact_name'],'artifact_sha256':row['artifact_sha256'],'manifest':json.loads(row['manifest_json']),'artifact_bytes':row['artifact_bytes'],'status':row['status'],'created_at':row['created_at'],'reused':reused}
    def verify(self,artifact_id,*,request_id,expected_digest,expected_width,expected_height):
        content=self.gen1.artifact_content(int(artifact_id));row=next((x for x in self.gen1.artifacts(100) if x.get('artifact_id')==artifact_id),None)
        if row is None:return {'verified':False,'method':'authoritative artifact registry + local digest/image reread','reason':'artifact registry row missing'}
        info=inspect_image_bytes(content['content']);manifest=dict(row.get('manifest') or {});verified=(content['sha256']==expected_digest==row.get('artifact_sha256')==info.sha256 and manifest.get('request_id')==request_id and manifest.get('artifact_kind')=='image_generation' and manifest.get('media_type')==info.media_type and int(manifest.get('width',-1))==info.width==expected_width and int(manifest.get('height',-1))==info.height==expected_height and manifest.get('artifact_sha256')==info.sha256)
        return {'verified':verified,'method':'authoritative artifact registry + local digest/image reread','artifact_id':artifact_id,'artifact_sha256':info.sha256,'media_type':info.media_type,'width':info.width,'height':info.height,'request_id':request_id}
    def generate(self,arguments,*,user_id,goal_id,task_run_id,trace_id,step_id):
        args=dict(arguments or {});prompt=str(args.get('prompt',''));classification=str(args.get('classification','PRIVATE')).upper();height=args.get('height',1024);width=args.get('width',1024);samples=args.get('samples',1);seed=args.get('seed',1);steps=args.get('steps',4)
        if classification not in {'PUBLIC','PRIVATE','SENSITIVE','HIGHLY_SENSITIVE','DEVICE_CONTROL'}:raise ValueError('invalid image-generation classification')
        if classification in BLOCKED_EXTERNAL_CLASSIFICATIONS:raise PermissionError('classification prohibits external image-generation transmission')
        request_id,digest=self.identity(owner_user_id=user_id,prompt=prompt,height=height,width=width,samples=samples,seed=seed,steps=steps,classification=classification,goal_id=goal_id,task_run_id=task_run_id,step_id=step_id);request=ImageGenerationRequest(request_id,user_id,prompt,height,width,samples,seed,steps,classification,goal_id,task_run_id,trace_id,step_id)
        state=self.store.image_generation_request(request_id);attempt=1 if state is None else int(state.get('attempt',0))+1
        existing=self._artifact_by_source(digest)
        if existing is not None:
            v=self.verify(existing['artifact_id'],request_id=request_id,expected_digest=existing['artifact_sha256'],expected_width=width,expected_height=height)
            if not v['verified']:raise RuntimeError('existing generated artifact verification failed')
            self.store.save_image_generation_request({'request_id':request_id,'owner_user_id':user_id,'status':'VERIFIED','attempt':max(1,attempt-1),'source_digest':digest,'artifact_id':existing['artifact_id'],'updated_at':now(),'provenance':request.safe_provenance()})
            return ImageGenerationResult(request_id,'VERIFIED',existing['artifact_id'],existing['artifact_name'],existing['artifact_sha256'],existing['manifest']['media_type'],existing['manifest']['width'],existing['manifest']['height'],existing['manifest']['provider'],existing['manifest']['model'],bool(existing['manifest']['fallback']),existing['manifest'].get('provider_request_id'),existing['manifest'].get('provider_status'),max(1,attempt-1),True,v,request.safe_provenance()|{'provider':existing['manifest']['provider'],'model':existing['manifest']['model'],'fallback':existing['manifest']['fallback']})
        self.store.save_image_generation_request({'request_id':request_id,'owner_user_id':user_id,'status':'GENERATING','attempt':attempt,'source_digest':digest,'artifact_id':None,'updated_at':now(),'provenance':request.safe_provenance()})
        try:
            routed=self.model_manager.generate_image(**request.provider_args());raw=routed['result'];info=inspect_image_bytes(raw['image_bytes'])
            if info.width!=width or info.height!=height:raise RuntimeError('provider image dimensions do not match requested dimensions')
            provider=dict(routed['provenance']);provider['provider_request_id']=raw.get('provider_request_id') or provider.get('provider_request_id');provider['provider_status']=raw.get('provider_status') or provider.get('provider_status');artifact=self._persist_artifact(request,digest,raw['image_bytes'],info,provider);verification=self.verify(artifact['artifact_id'],request_id=request_id,expected_digest=info.sha256,expected_width=width,expected_height=height)
            if not verification['verified']:raise RuntimeError('generated image artifact verification failed')
        except Exception as exc:
            self.store.save_image_generation_request({'request_id':request_id,'owner_user_id':user_id,'status':'FAILED','attempt':attempt,'source_digest':digest,'artifact_id':None,'updated_at':now(),'failure':{'type':type(exc).__name__},'provenance':request.safe_provenance()});raise
        self.store.save_image_generation_request({'request_id':request_id,'owner_user_id':user_id,'status':'VERIFIED','attempt':attempt,'source_digest':digest,'artifact_id':artifact['artifact_id'],'updated_at':now(),'provenance':request.safe_provenance()|{'provider':provider['provider'],'model':provider['model'],'fallback':provider['fallback'],'provider_request_id':provider.get('provider_request_id'),'provider_status':provider.get('provider_status')}})
        return ImageGenerationResult(request_id,'VERIFIED',artifact['artifact_id'],artifact['artifact_name'],artifact['artifact_sha256'],info.media_type,info.width,info.height,provider['provider'],provider['model'],bool(provider['fallback']),provider.get('provider_request_id'),provider.get('provider_status'),attempt,artifact['reused'],verification,request.safe_provenance()|{'provider':provider['provider'],'model':provider['model'],'fallback':provider['fallback']})
    def invoke(self,arguments,**context):
        result=self.generate(arguments,**context);return {'output':result.to_dict(),'verification':result.verification}
    def health(self):return self.model_manager.status('image_generation')

# Legacy injected provider harness retained for backward compatibility with earlier tests.
class ImageGenerationRuntime:
    def __init__(self,provider=None):self.provider=provider
    def health(self):return {'status':'CONNECTED' if self.provider else 'EXTERNALLY_BLOCKED'}
    def generate(self,prompt,*,approved=True,goal_id=None,project_id=None,task_id=None):
        if self.provider is None:raise RuntimeError('external_dependency:image_generation_provider')
        if not approved:raise PermissionError('approval_required')
        result=self.provider(prompt)
        if not isinstance(result,dict) or 'artifact' not in result:raise RuntimeError('invalid_image_provider_result')
        out=dict(result);out['provenance']={'provider':getattr(self.provider,'name',type(self.provider).__name__),'generated_at':now(),'goal_id':goal_id,'project_id':project_id,'task_id':task_id}
        return out
