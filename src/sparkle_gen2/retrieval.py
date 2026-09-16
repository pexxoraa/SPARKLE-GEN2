from __future__ import annotations

class SemanticRetrievalRuntime:
    def __init__(self,embedder=None,reranker=None):self.embedder=embedder;self.reranker=reranker
    def health(self):return {'embedding':'CONNECTED' if self.embedder else 'EXTERNALLY_BLOCKED','reranking':'CONNECTED' if self.reranker else 'EXTERNALLY_BLOCKED'}
    def retrieve(self,query,documents,k=5):
        if self.embedder is None:raise RuntimeError('external_dependency:embedding_provider')
        if not 1<=int(k)<=100:raise ValueError('k out of range')
        q=self.embedder(query);scored=[]
        for doc in documents:
            v=self.embedder(doc['text']);score=sum(a*b for a,b in zip(q,v));scored.append((score,doc))
        scored.sort(key=lambda x:-x[0]);items=[d for _,d in scored[:max(k*2,k)]]
        if self.reranker is not None:items=self.reranker(query,items)[:k]
        else:items=items[:k]
        return items

class RetrievalQualityEvaluator:
    """Independent labeled relevance evaluation; never trusts provider quality claims."""
    def evaluate(self,runtime,cases,*,k=5):
        if not cases:raise ValueError('evaluation cases required')
        reciprocal=[];recall=[]
        details=[]
        for case in cases:
            expected=set(case['relevant_ids']);ranked=runtime.retrieve(case['query'],case['documents'],k=k);ids=[d['id'] for d in ranked]
            hits=[i for i,x in enumerate(ids,1) if x in expected]
            reciprocal.append(1.0/min(hits) if hits else 0.0);recall.append(len(expected & set(ids))/len(expected) if expected else 1.0)
            details.append({'query':case['query'],'ranked_ids':ids,'relevant_ids':sorted(expected),'verified_by':'labeled_relevance'})
        return {'mrr':sum(reciprocal)/len(reciprocal),'recall_at_k':sum(recall)/len(recall),'cases':details,'verified':True}

class PersistentSemanticIndex:
    def __init__(self,store,embedder,reranker=None):
        if embedder is None:raise RuntimeError('external_dependency:embedding_provider')
        self.store=store;self.embedder=embedder;self.reranker=reranker
    def upsert(self,document_id,text,*,metadata=None):
        vector=list(self.embedder(text));payload={'id':document_id,'text':str(text),'vector':vector,'metadata':dict(metadata or {})};self.store.save_semantic_document(document_id,payload);return payload
    def search(self,query,*,k=5):
        if not 1<=int(k)<=100:raise ValueError('k out of range')
        q=list(self.embedder(query));scored=[]
        for doc in self.store.semantic_documents():
            v=doc.get('vector',[]);score=sum(a*b for a,b in zip(q,v));scored.append((score,doc))
        scored.sort(key=lambda x:-x[0]);items=[d|{'vector_score':score} for score,d in scored[:max(k*2,k)]]
        if self.reranker is not None:items=self.reranker(query,items)[:k]
        else:items=items[:k]
        return items
    def context_items(self,query,*,k=5):
        from .context_engine import ContextItem
        return [ContextItem('semantic',d['id'],d['text'],1.0,max(0.0,min(1.0,float(d.get('vector_score',0)))), 'ALLOW',{'document_id':d['id'],'metadata':d.get('metadata',{})}) for d in self.search(query,k=k)]
