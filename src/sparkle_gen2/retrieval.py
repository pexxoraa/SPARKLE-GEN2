from __future__ import annotations

class SemanticRetrievalRuntime:
    def __init__(self,embedder=None,reranker=None):self.embedder=embedder;self.reranker=reranker
    def health(self):return {'embedding':'CONNECTED' if self.embedder else 'EXTERNALLY_BLOCKED','reranking':'CONNECTED' if self.reranker else 'EXTERNALLY_BLOCKED'}
    def retrieve(self,query,documents,k=5):
        if self.embedder is None:raise RuntimeError('external_dependency:embedding_provider')
        q=self.embedder(query);scored=[]
        for doc in documents:
            v=self.embedder(doc['text']);score=sum(a*b for a,b in zip(q,v));scored.append((score,doc))
        scored.sort(key=lambda x:-x[0]);items=[d for _,d in scored[:max(k*2,k)]]
        if self.reranker is not None:items=self.reranker(query,items)[:k]
        else:items=items[:k]
        return items
