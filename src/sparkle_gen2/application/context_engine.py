from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(slots=True)
class ContextItem:
    source: str
    key: str
    value: str
    freshness: float = 1.0
    relevance: float = 1.0
    permission: str = "ALLOW"
    provenance: dict[str, Any] = field(default_factory=dict)

class PersonalContextEngine:
    def __init__(self, *, max_items: int = 20, max_chars: int = 12000):
        self.max_items=max_items; self.max_chars=max_chars
    def build(self, goal: str, sources: dict[str, list[ContextItem]]) -> dict[str, Any]:
        candidates=[]
        terms={t.lower() for t in goal.split() if len(t)>2}
        for source,items in sources.items():
            for item in items:
                if item.permission != "ALLOW": continue
                overlap=sum(1 for t in terms if t in item.value.lower() or t in item.key.lower())
                score=(item.relevance*0.6)+(item.freshness*0.3)+min(overlap,3)*0.1
                candidates.append((score,source,item))
        candidates.sort(key=lambda x:(-x[0],x[1],x[2].key))
        selected=[]; chars=0
        for score,source,item in candidates[:self.max_items*2]:
            text=item.value[:3000]
            if chars+len(text)>self.max_chars: continue
            selected.append({'source':source,'key':item.key,'value':text,'score':round(score,4),'provenance':item.provenance})
            chars+=len(text)
            if len(selected)>=self.max_items: break
        return {'goal':goal,'items':selected,'item_count':len(selected),'char_count':chars}
