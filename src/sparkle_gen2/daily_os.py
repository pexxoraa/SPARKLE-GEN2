from __future__ import annotations

class DailyOperatingSystem:
    SOURCE_IMPORTANCE={'goals':1.0,'tasks':1.0,'calendar':.95,'email':.8,'projects':.85,'recent_activity':.65,'devices':.7,'world_state':.65,'research':.6,'learning':.55,'memory':.5,'preferences':.5}
    def build_brief(self,items):
        normalized=[]
        for item in items:
            urgency=float(item.get('urgency',0));importance=float(item.get('importance',0));relevance=float(item.get('relevance',1))
            score=urgency*0.45+importance*0.4+relevance*0.15
            normalized.append((score,item))
        normalized.sort(key=lambda x:(-x[0],str(x[1].get('title',''))))
        return [{'title':i.get('title','Untitled'),'kind':i.get('kind','item'),'score':round(s,3),'action':i.get('action')} for s,i in normalized]
    def from_context(self,context,*,max_items=10):
        if not 1<=int(max_items)<=50:raise ValueError('max_items out of range')
        items=[]
        for entry in context.get('items',[]):
            source=str(entry.get('source','item'));relevance=min(1.0,max(0.0,float(entry.get('score',.5))))
            importance=self.SOURCE_IMPORTANCE.get(source,.5);value=str(entry.get('value',''))
            urgency=.9 if any(x in value.lower() for x in ('deadline','today','overdue','failure','fault')) else .3
            items.append({'title':str(entry.get('key') or source),'kind':source,'urgency':urgency,'importance':importance,'relevance':relevance,'action':'review' if source in {'email','recent_activity','research'} else 'continue'})
        return self.build_brief(items)[:max_items]
