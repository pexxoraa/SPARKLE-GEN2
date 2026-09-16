from __future__ import annotations
from datetime import datetime

class DailyOperatingSystem:
    def build_brief(self,items):
        normalized=[]
        for item in items:
            urgency=float(item.get('urgency',0));importance=float(item.get('importance',0));relevance=float(item.get('relevance',1))
            score=urgency*0.45+importance*0.4+relevance*0.15
            normalized.append((score,item))
        normalized.sort(key=lambda x:(-x[0],str(x[1].get('title',''))))
        return [{'title':i.get('title','Untitled'),'kind':i.get('kind','item'),'score':round(s,3),'action':i.get('action')} for s,i in normalized]
