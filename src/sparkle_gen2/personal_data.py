from __future__ import annotations

SOURCE_TO_TOOL={
    'memory':'memory_search',
    'knowledge':'knowledge_search',
    'projects':'project_search',
    'tasks':'project_tasks',
    'learning':'learning_progress',
    'research':'research_workspace',
}
class PersonalDataOrchestrator:
    def __init__(self,gen1):self.gen1=gen1
    def available_sources(self):
        tools=set(self.gen1.health().get('tools',[]))
        return {source:(tool in tools) for source,tool in SOURCE_TO_TOOL.items()}
    def retrieve(self,source,query,*,limit=5):
        if source not in SOURCE_TO_TOOL:raise KeyError(source)
        tool=SOURCE_TO_TOOL[source]
        if tool not in set(self.gen1.health().get('tools',[])):raise RuntimeError(f'unsupported_source:{source}')
        args={'query':query,'limit':limit}
        if tool=='project_tasks':args={'project':query}
        elif tool=='learning_progress':args={'course':query}
        elif tool=='research_workspace':args={'project':query,'report':False}
        obs=self.gen1.invoke(tool,args)
        if not obs.ok:raise RuntimeError(f'source_failed:{source}')
        return {'source':source,'tool':tool,'output':obs.output,'verification':obs.verification}
