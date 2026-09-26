from __future__ import annotations
import hashlib,uuid
from dataclasses import asdict,dataclass,field

SUPPORTED_TRANSPORT=frozenset({'text','image','audio','document','video','screen','camera'})
ROUTABLE_MODALITIES=frozenset({'text','image','audio','document'})
MAX_BYTES={'text':1_000_000,'image':20_000_000,'audio':20_000_000,'document':25_000_000,'video':50_000_000,'screen':20_000_000,'camera':20_000_000}
MIME_ALLOWLIST={
    'text':frozenset({'text/plain','text/markdown'}),
    'image':frozenset({'image/png','image/jpeg','image/webp'}),
    'audio':frozenset({'audio/wav','audio/x-wav','audio/wave'}),
    'document':frozenset({'application/pdf','text/plain','text/markdown'}),
    'video':frozenset({'video/mp4','video/webm'}),
    'screen':frozenset({'image/png','image/jpeg'}),
    'camera':frozenset({'image/png','image/jpeg'}),
}

@dataclass(slots=True)
class MediaInput:
    media_id:str
    modality:str
    location:str
    size_bytes:int
    semantic_verified:bool=False
    provider:str|None=None
    mime_type:str|None=None
    sha256:str|None=None
    metadata:dict=field(default_factory=dict)
    def to_dict(self):return asdict(self)

class MultimodalGateway:
    def validate_transport(self,item:MediaInput):
        if item.modality not in SUPPORTED_TRANSPORT:raise ValueError('unsupported modality')
        limit=MAX_BYTES[item.modality]
        if isinstance(item.size_bytes,bool) or not isinstance(item.size_bytes,int) or item.size_bytes<0 or item.size_bytes>limit:raise ValueError('invalid media size')
        if item.mime_type is not None and item.mime_type not in MIME_ALLOWLIST[item.modality]:raise ValueError('unsupported media MIME type')
        if item.sha256 is not None and (not isinstance(item.sha256,str) or len(item.sha256)!=64 or any(c not in '0123456789abcdef' for c in item.sha256.lower())):raise ValueError('invalid media digest')
        return True
    @staticmethod
    def _detect(data:bytes,mime_type:str|None):
        mt=str(mime_type or '').lower().strip()
        if data.startswith(b'\x89PNG\r\n\x1a\n'):return 'image','image/png'
        if data.startswith(b'\xff\xd8'):return 'image','image/jpeg'
        if data.startswith(b'RIFF') and len(data)>=12 and data[8:12]==b'WAVE':return 'audio','audio/wav'
        if data.startswith(b'RIFF') and len(data)>=12 and data[8:12]==b'WEBP':return 'image','image/webp'
        if data.startswith(b'%PDF-'):return 'document','application/pdf'
        if mt in MIME_ALLOWLIST['text']:
            try:data.decode('utf-8')
            except UnicodeDecodeError:raise ValueError('text media is not valid UTF-8') from None
            return 'text',mt
        binary_declared=set().union(MIME_ALLOWLIST['image'],MIME_ALLOWLIST['audio'],MIME_ALLOWLIST['document'],MIME_ALLOWLIST['video'],MIME_ALLOWLIST['screen'],MIME_ALLOWLIST['camera'])-MIME_ALLOWLIST['text']
        if mt in binary_declared:raise ValueError('declared binary MIME type does not match recognized content')
        for modality,types in MIME_ALLOWLIST.items():
            if mt in types:return modality,mt
        raise ValueError('media type cannot be detected safely')
    def prepare_bytes(self,data,*,modality=None,mime_type=None,media_id=None,provider=None):
        import io,warnings,wave
        if not isinstance(data,(bytes,bytearray,memoryview)):raise TypeError('media input must be bytes-like')
        size=data.nbytes if isinstance(data,memoryview) else len(data)
        if not size or size>max(MAX_BYTES.values()):raise ValueError('media payload exceeds byte limit')
        raw=bytes(data);detected,normalized_mime=self._detect(raw,mime_type)
        chosen=str(modality or detected)
        if chosen not in ROUTABLE_MODALITIES or chosen!=detected:raise ValueError('declared modality does not match media content')
        declared=str(mime_type or normalized_mime).lower().strip()
        if declared in {'audio/x-wav','audio/wave'}:declared='audio/wav'
        if declared!=normalized_mime:raise ValueError('declared MIME type does not match media content')
        if size>MAX_BYTES[chosen]:raise ValueError('media payload exceeds modality byte limit')
        original_digest=hashlib.sha256(raw).hexdigest();details={}
        if chosen=='image':
            from PIL import Image,ImageOps
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error',Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(raw)) as picture:
                        expected={'image/png':'PNG','image/jpeg':'JPEG','image/webp':'WEBP'}[normalized_mime]
                        if picture.format!=expected or getattr(picture,'n_frames',1)!=1:raise ValueError('unsupported image container')
                        width,height=picture.size
                        if not 1<=width<=8192 or not 1<=height<=8192 or width*height>8_388_608:raise ValueError('image pixel budget exceeded')
                        picture.verify()
                    with Image.open(io.BytesIO(raw)) as picture:
                        oriented=ImageOps.exif_transpose(picture)
                        converted=oriented.convert('RGB' if expected=='JPEG' else 'RGBA')
                        clean=Image.frombytes(converted.mode,converted.size,converted.tobytes())
                        output=io.BytesIO()
                        clean.save(output,format=expected,**({'lossless':True} if expected=='WEBP' else {}))
                        raw=output.getvalue();details={'width':clean.width,'height':clean.height}
                        clean.close();converted.close();oriented.close()
            except Exception:raise ValueError('invalid or oversized image media') from None
        elif chosen=='audio':
            try:
                with wave.open(io.BytesIO(raw),'rb') as sound:
                    if sound.getnchannels()!=1 or sound.getsampwidth()!=2 or sound.getframerate()!=16000 or sound.getcomptype()!='NONE':raise ValueError('unsupported audio format')
                    frames=sound.getnframes()
                    if not 1<=frames<=16000*30:raise ValueError('audio duration exceeds bound')
                    pcm=sound.readframes(frames)
                    if len(pcm)!=frames*2:raise ValueError('truncated audio')
                output=io.BytesIO()
                with wave.open(output,'wb') as sound:
                    sound.setnchannels(1);sound.setsampwidth(2);sound.setframerate(16000);sound.writeframes(pcm)
                raw=output.getvalue();details={'sample_rate':16000,'channels':1,'duration_seconds':frames/16000}
            except Exception:raise ValueError('invalid or oversized audio media') from None
        if len(raw)>MAX_BYTES[chosen]:raise ValueError('normalized media exceeds byte limit')
        mid=str(media_id or ('media_'+uuid.uuid4().hex))
        if not mid or len(mid)>128 or any(not(c.isalnum() or c in '_-') for c in mid):raise ValueError('media_id invalid')
        item=MediaInput(mid,chosen,'memory://'+mid,len(raw),False,provider,normalized_mime,hashlib.sha256(raw).hexdigest(),
            {'source':'bounded_bytes','metadata_stripped':chosen in {'image','audio'},'source_sha256':original_digest,**details})
        self.validate_transport(item);return item,raw
    def normalize_bytes(self,data,**kwargs):
        item,_=self.prepare_bytes(data,**kwargs);return item
    def semantic_status(self,item:MediaInput):
        self.validate_transport(item);return 'LIVE_VERIFIED' if item.semantic_verified and item.provider else 'EXTERNALLY_BLOCKED'
    def route(self,item:MediaInput,model_manager):
        self.validate_transport(item)
        if item.modality not in ROUTABLE_MODALITIES:return {'status':'BLOCKED','reason':'modality_has_no_registered_model_input'}
        if item.modality=='text':route=model_manager.route(['reasoning'],input_modalities=['text'],output_modalities=['text'])
        elif item.modality=='image':route=model_manager.route(['multimodal'],input_modalities=['image'],output_modalities=['text'])
        elif item.modality=='audio':route=model_manager.route(['voice'],input_modalities=['audio'],output_modalities=['audio','text'])
        else:route=model_manager.route(['multimodal'],input_modalities=['document'],output_modalities=['text'])
        return {'status':route.status if route.selected is not None else 'BLOCKED','route':route.to_dict(),'media':{'media_id':item.media_id,'modality':item.modality,'mime_type':item.mime_type,'size_bytes':item.size_bytes,'sha256':item.sha256}}
