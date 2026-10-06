from __future__ import annotations
from time import monotonic

SOURCE_TO_TOOL={
    'memory':'memory_search',
    'knowledge':'knowledge_search',
    'projects':'project_search',
    'tasks':'project_tasks',
    'learning':'learning_progress',
    'research':'research_workspace',
}
class PersonalDataOrchestrator:
    def __init__(self,gen1):
        self.gen1=gen1
        self._tools_cache=set()
        self._tools_cache_at=0.0
        self._tools_ttl=5.0

    def _tools(self):
        stamp=monotonic()
        if self._tools_cache_at > 0.0 and stamp-self._tools_cache_at < self._tools_ttl:
            return set(self._tools_cache)
        tools=set(self.gen1.health().get('tools',[]))
        self._tools_cache=tools
        self._tools_cache_at=stamp
        return set(tools)

    def invalidate_health_cache(self):
        self._tools_cache=set()
        self._tools_cache_at=0.0

    def available_sources(self):
        tools=self._tools()
        return {source:(tool in tools) for source,tool in SOURCE_TO_TOOL.items()}

    def retrieve(self,source,query,*,limit=5):
        if source not in SOURCE_TO_TOOL:raise KeyError(source)
        tool=SOURCE_TO_TOOL[source]
        if tool not in self._tools():raise RuntimeError(f'unsupported_source:{source}')
        args={'query':query,'limit':limit}
        if tool=='project_tasks':args={'project':query}
        elif tool=='learning_progress':args={'course':query}
        elif tool=='research_workspace':args={'project':query,'report':False}
        obs=self.gen1.invoke(tool,args)
        if not obs.ok:raise RuntimeError(f'source_failed:{source}')
        return {'source':source,'tool':tool,'output':obs.output,'verification':obs.verification}
