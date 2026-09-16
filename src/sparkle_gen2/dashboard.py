from __future__ import annotations
import html,json

class ReadOnlyDashboard:
    def snapshot(self,*,capabilities=None,tasks=None,connectors=None,diagnostics=None):
        return {'capabilities':capabilities or [],'tasks':tasks or [],'connectors':connectors or [],'diagnostics':diagnostics or {}}
    def render_html(self,snapshot):
        data=html.escape(json.dumps(snapshot,sort_keys=True,ensure_ascii=False))
        return '<!doctype html><html><head><meta charset="utf-8"><title>SPARKLE</title></head><body><h1>SPARKLE</h1><pre>'+data+'</pre></body></html>'
