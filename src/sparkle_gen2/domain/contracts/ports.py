"""Small ports used by application services; implementations live in infrastructure."""
from __future__ import annotations
from typing import Any, Protocol

class StorePort(Protocol):
    def __getattr__(self,name:str)->Any: ...

class ModelPort(Protocol):
    def complete(self,*args:Any,**kwargs:Any)->Any: ...

class ConnectorPort(Protocol):
    def __getattr__(self,name:str)->Any: ...
