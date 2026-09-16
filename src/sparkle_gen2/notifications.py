from __future__ import annotations
import uuid
from dataclasses import asdict,dataclass
from .core_time import now

@dataclass(slots=True)
class Notification:
    notification_id:str;kind:str;title:str;body:str;priority:str;status:str;created_at:str
    def to_dict(self):return asdict(self)
class NotificationCenter:
    def __init__(self,store=None):
        self.store=store;self.items={}
        if store is not None:
            for d in store.notifications():self.items[d['notification_id']]=Notification(**d)
    def _save(self,n):
        self.items[n.notification_id]=n
        if self.store is not None:self.store.save_notification(n)
        return n
    def create(self,kind,title,body,priority='NORMAL'):
        if priority not in {'LOW','NORMAL','HIGH','CRITICAL'}:raise ValueError('invalid priority')
        return self._save(Notification(uuid.uuid4().hex,kind,title,body,priority,'UNREAD',now()))
    def read(self,nid):
        n=self.items[nid];n.status='READ';return self._save(n)
    def list_unread(self):return [n for n in self.items.values() if n.status=='UNREAD']
