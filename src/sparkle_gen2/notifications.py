from __future__ import annotations
import uuid
from dataclasses import asdict,dataclass
from .core_time import now

@dataclass(slots=True)
class Notification:
    notification_id:str
    kind:str
    title:str
    body:str
    priority:str
    status:str
    created_at:str
    def to_dict(self):return asdict(self)
class NotificationCenter:
    def __init__(self):self.items={}
    def create(self,kind,title,body,priority='NORMAL'):
        if priority not in {'LOW','NORMAL','HIGH','CRITICAL'}:raise ValueError('invalid priority')
        n=Notification(uuid.uuid4().hex,kind,title,body,priority,'UNREAD',now());self.items[n.notification_id]=n;return n
    def read(self,nid):self.items[nid].status='READ';return self.items[nid]
    def list_unread(self):return [n for n in self.items.values() if n.status=='UNREAD']
