from __future__ import annotations
from dataclasses import asdict, dataclass

SUPPORTED_TRANSPORT={'text','image','audio','document','video','screen','camera'}
@dataclass(slots=True)
class MediaInput:
    media_id:str
    modality:str
    location:str
    size_bytes:int
    semantic_verified:bool=False
    provider:str|None=None
    def to_dict(self): return asdict(self)

class MultimodalGateway:
    def validate_transport(self,item:MediaInput):
        if item.modality not in SUPPORTED_TRANSPORT: raise ValueError('unsupported modality')
        if item.size_bytes<0 or item.size_bytes>50_000_000: raise ValueError('invalid media size')
        return True
    def semantic_status(self,item:MediaInput):
        self.validate_transport(item)
        return 'LIVE_VERIFIED' if item.semantic_verified and item.provider else 'EXTERNALLY_BLOCKED'
