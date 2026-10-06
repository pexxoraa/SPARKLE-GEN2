from __future__ import annotations
import csv,hashlib,io,json,mimetypes,re,subprocess,uuid,zipfile
from dataclasses import asdict,dataclass,field
from datetime import UTC,datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from ...application.context_engine import ContextItem
from ...application.retrieval import DeterministicRetrievalRuntime

PROCESSING_VERSION='document-intelligence-v2'
CLASSIFICATIONS=frozenset({'PUBLIC','PRIVATE','SENSITIVE','HIGHLY_SENSITIVE','DEVICE_CONTROL'})
STATUS=frozenset({'RECEIVED','VALIDATING','EXTRACTING','STRUCTURING','READY','FAILED','BLOCKED'})
TEXT_TYPES={'.txt','text/plain'}
CSV_TYPES={'.csv','text/csv','application/csv'}
IMAGE_EXTS={'.png','.jpg','.jpeg','.gif','.webp','.bmp','.tif','.tiff'}
MAX_CELL_CHARS=4000
PDFINFO=Path('/usr/bin/pdfinfo')
PDFTOTEXT=Path('/usr/bin/pdftotext')
DOCUMENT_SUBPROCESS_ENV={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8'}

@dataclass(slots=True)
class SourceLocation:
    kind:str
    index:int|None=None
    label:str|None=None
    path:str|None=None
    row_start:int|None=None
    row_end:int|None=None
    char_start:int|None=None
    char_end:int|None=None
    def to_dict(self):return asdict(self)

@dataclass(slots=True)
class DocumentChunk:
    chunk_id:str
    text:str
    kind:str
    location:dict[str,Any]
    metadata:dict[str,Any]=field(default_factory=dict)
    def to_dict(self):return asdict(self)

@dataclass(slots=True)
class DocumentRecord:
    document_id:str
    owner_user_id:str
    source:dict[str,Any]
    media_type:str
    filename:str
    size:int
    content_digest:str
    created_at:str
    updated_at:str
    status:str
    classification:str
    units:dict[str,int]
    structured_content:dict[str,Any]
    chunks:list[dict[str,Any]]
    metadata:dict[str,Any]
    provenance:dict[str,Any]
    processing_version:str=PROCESSING_VERSION
    failure:dict[str,Any]|None=None
    links:list[dict[str,str]]=field(default_factory=list)
    def to_dict(self):return asdict(self)

class DocumentIntelligenceService:
    def __init__(self,store,*,allowed_roots:list[str|Path]|None=None,max_bytes:int=20_000_000,max_units:int=1000,max_extracted_chars:int=2_000_000,chunk_chars:int=1800,max_chunks:int=1000,model_manager=None,allow_external_sensitive:bool=False):
        self.store=store;self.allowed_roots=[Path(x).expanduser().resolve() for x in (allowed_roots or [])];self.max_bytes=int(max_bytes);self.max_units=int(max_units);self.max_extracted_chars=int(max_extracted_chars);self.chunk_chars=int(chunk_chars);self.max_chunks=int(max_chunks);self.model_manager=model_manager;self.allow_external_sensitive=bool(allow_external_sensitive);self.retriever=DeterministicRetrievalRuntime()
        if not 1<=self.max_bytes<=200_000_000:raise ValueError('document max_bytes out of range')
        if not 1<=self.max_units<=10000 or not 256<=self.chunk_chars<=10000 or not 1<=self.max_chunks<=10000:raise ValueError('document bounds invalid')
    @staticmethod
    def _now():return datetime.now(UTC).isoformat()
    def _path(self,value):
        p=Path(value).expanduser()
        if not p.is_absolute():raise ValueError('document path must be absolute')
        if p.is_symlink():raise ValueError('document symlink sources are not allowed')
        p=p.resolve(strict=True)
        if not p.is_file():raise ValueError('document source must be a file')
        if not self.allowed_roots or not any(root==p.parent or root in p.parents for root in self.allowed_roots):raise PermissionError('document path is outside authorized roots')
        return p
    @staticmethod
    def _media(path:Path):
        ext=path.suffix.lower();known={'.pdf':'application/pdf','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','.pptx':'application/vnd.openxmlformats-officedocument.presentationml.presentation','.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','.csv':'text/csv','.txt':'text/plain'}
        return known.get(ext,mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
    @staticmethod
    def _identity(owner,digest):return 'doc_'+hashlib.sha256(f'{owner}\0{digest}\0{PROCESSING_VERSION}'.encode()).hexdigest()[:32]
    def _save(self,r):self.store.save_document_record(r)
    def get(self,document_id,*,user_id):
        r=self.store.load_document_record(document_id)
        if r.owner_user_id!=user_id:raise PermissionError('document owner mismatch')
        return r
    def list(self,*,user_id):return [r for r in self.store.document_records() if r.owner_user_id==user_id]
    def ingest_named(self,filename,*,user_id,classification='PRIVATE'):
        if not isinstance(filename,str) or not filename.strip() or Path(filename).name!=filename or '/' in filename or '\\' in filename:raise ValueError('document filename must be a basename inside an authorized document root')
        matches=[root/filename for root in self.allowed_roots if (root/filename).is_file() and not (root/filename).is_symlink()]
        if len(matches)!=1:raise ValueError('document filename is unavailable or ambiguous')
        return self.ingest_path(matches[0],user_id=user_id,classification=classification)
    def invoke_ingest(self,args,*,user_id):
        r=self.ingest_named(str(args.get('filename','')),user_id=user_id,classification=str(args.get('classification','PRIVATE')))
        reread=self.get(r.document_id,user_id=user_id);verified=(reread.status=='READY' and reread.content_digest==r.content_digest and reread.provenance.get('source_digest')==r.content_digest)
        return {'output':reread.to_dict(),'verification':{'verified':verified,'method':'re-read persisted document identity, digest, processing version, and READY state','document_id':r.document_id,'status':reread.status}}

    def ingest_path(self,path,*,user_id,classification='PRIVATE'):
        if classification not in CLASSIFICATIONS:raise ValueError('invalid document classification')
        if not isinstance(user_id,str) or not user_id.strip():raise ValueError('document owner is required')
        p=self._path(path);size=p.stat().st_size
        if size>self.max_bytes:raise ValueError('document exceeds size limit')
        content=p.read_bytes();digest=hashlib.sha256(content).hexdigest();did=self._identity(user_id,digest)
        try:
            existing=self.store.load_document_record(did)
            if existing.content_digest==digest and existing.processing_version==PROCESSING_VERSION:return existing
        except KeyError:pass
        stamp=self._now();media=self._media(p);record=DocumentRecord(did,user_id,{'kind':'local_path','filename':p.name},media,p.name,size,digest,stamp,stamp,'RECEIVED',classification,{}, {}, [], {'filename':p.name}, {'source_digest':digest,'processing_version':PROCESSING_VERSION,'extractor':'pending'})
        self._save(record)
        try:
            record.status='VALIDATING';record.updated_at=self._now();self._save(record);self._validate_signature(p,media)
            record.status='EXTRACTING';record.updated_at=self._now();self._save(record);structured,meta,extractor=self._extract(p,media,classification=classification)
            record.status='STRUCTURING';record.updated_at=self._now();self._save(record);chunks,units=self._structure(structured,did)
            model_provenance=dict(meta.pop('_model_provenance',{}));record.structured_content=structured;record.chunks=[c.to_dict() for c in chunks];record.units=units;record.metadata=meta|{'filename':p.name};record.provenance={'source_digest':digest,'processing_version':PROCESSING_VERSION,'extractor':extractor,'local_only_extraction':not bool(model_provenance),'model':model_provenance or None};record.status='READY';record.updated_at=self._now();self._save(record);return record
        except ExternalSemanticBlock as exc:
            record.status='BLOCKED';record.failure={'category':'EXTERNALLY_BLOCKED','reason':str(exc)};record.updated_at=self._now();record.provenance={'source_digest':digest,'processing_version':PROCESSING_VERSION,'extractor':'none','local_only_extraction':True};self._save(record);return record
        except UnsupportedFormat as exc:
            record.status='BLOCKED';record.failure={'category':'UNSUPPORTED_FORMAT','reason':str(exc)};record.updated_at=self._now();record.provenance={'source_digest':digest,'processing_version':PROCESSING_VERSION,'extractor':'none','local_only_extraction':True};self._save(record);return record
        except Exception as exc:
            record.status='FAILED';record.failure={'category':'EXTRACTION_FAILURE','error_type':type(exc).__name__,'reason':str(exc)[:300]};record.updated_at=self._now();self._save(record);return record
    def _validate_signature(self,p,media):
        head=p.read_bytes()[:8]
        if media=='application/pdf' and not head.startswith(b'%PDF-'):raise ValueError('malformed PDF signature')
        if p.suffix.lower() in {'.docx','.pptx','.xlsx'}:
            if not head.startswith(b'PK'):raise ValueError('malformed OOXML container')
            with zipfile.ZipFile(p) as z:
                members=z.infolist()
                if len(members)>5000 or sum(x.file_size for x in members)>50_000_000:raise ValueError('OOXML package exceeds extraction bounds')
                if '[Content_Types].xml' not in z.namelist():raise ValueError('invalid OOXML package')
        if p.suffix.lower() in IMAGE_EXTS:
            supported={'image/png':b'\x89PNG\r\n\x1a\n','image/jpeg':b'\xff\xd8\xff','image/gif':b'GIF'}
            if media not in supported:raise ExternalSemanticBlock('image transport is supported but this image media type is not supported by the configured multimodal adapter')
            if not head.startswith(supported[media]):raise ValueError('malformed image signature')
        if p.suffix.lower() not in {'.pdf','.docx','.pptx','.xlsx','.csv','.txt'} and p.suffix.lower() not in IMAGE_EXTS:raise UnsupportedFormat('unsupported document format')
    def _extract(self,p,media,*,classification='PRIVATE'):
        ext=p.suffix.lower()
        if ext=='.pdf':return self._pdf(p)
        if ext=='.docx':return self._docx(p)
        if ext=='.pptx':return self._pptx(p)
        if ext=='.xlsx':return self._xlsx(p)
        if ext=='.csv':return self._csv(p)
        if ext=='.txt':return self._text(p)
        if ext in IMAGE_EXTS:return self._image(p,media,classification=classification)
        raise UnsupportedFormat('unsupported document format')
    def _image(self,p,media,*,classification):
        if classification in {'SENSITIVE','HIGHLY_SENSITIVE','DEVICE_CONTROL'} and not self.allow_external_sensitive:raise ExternalSemanticBlock('document classification prohibits external multimodal transmission')
        if self.model_manager is None:raise ExternalSemanticBlock('semantic image understanding requires a configured multimodal provider')
        route=self.model_manager.route(['multimodal','reasoning'],input_modalities=['text','image'],output_modalities=['text'])
        if route.selected is None:raise ExternalSemanticBlock('semantic image understanding requires an available multimodal provider')
        from sparkle.contracts import Message,ModelRequest
        from sparkle.content import ContentEnvelope,ContentPart
        prompt='Describe the visible contents of this image factually and concisely. Report only observable content; do not infer identity, intent, private attributes, or hidden information.'
        envelope=ContentEnvelope([ContentPart.text(prompt),ContentPart.binary('image',p.read_bytes(),media_type=media)])
        request=ModelRequest(messages=[Message(role='user',content=envelope)],temperature=0.0,max_output_tokens=512,thinking=False,metadata={'operation':'gen2_document_image_understanding','required_capabilities':['multimodal','reasoning']})
        result=self.model_manager.complete(request,['multimodal','reasoning'],input_modalities=['text','image'],output_modalities=['text']);text=str(result['response'].text).strip()
        if not text:raise ValueError('multimodal provider returned empty image description')
        prov=dict(result.get('provenance') or {})
        return {'type':'image','description':text,'media_type':media},{'semantic_understanding':'multimodal','_model_provenance':prov},'nvidia-multimodal/image'

    def _pdf(self,p):
        if not PDFINFO.is_file() or not PDFTOTEXT.is_file():raise ExternalSemanticBlock('required local PDF extraction helpers are unavailable')
        info=subprocess.run([str(PDFINFO),str(p)],stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=15,check=False,env=DOCUMENT_SUBPROCESS_ENV)
        if info.returncode!=0:raise ValueError('pdfinfo could not validate document')
        run=subprocess.run([str(PDFTOTEXT),'-f','1','-l',str(self.max_units),'-layout',str(p),'-'],stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=30,check=False,env=DOCUMENT_SUBPROCESS_ENV)
        if run.returncode!=0:raise ValueError('pdftotext extraction failed')
        raw=run.stdout
        if not raw.strip():raise ExternalSemanticBlock('PDF contains no extractable text; OCR/vision is externally blocked')
        pages=[]
        for i,text in enumerate(raw.split('\f'),1):
            text=text.strip('\n\r ')
            if text:pages.append({'page':i,'blocks':[{'type':'text','text':text}]})
            if len(pages)>=self.max_units:break
        meta={}
        for line in info.stdout.splitlines():
            if ':' in line:
                k,v=line.split(':',1);meta[k.strip().lower().replace(' ','_')]=v.strip()
        return {'type':'pdf','pages':pages},meta,'pdftotext/pdfinfo'
    @staticmethod
    def _zip_xml(z,name):return ET.fromstring(z.read(name))
    @staticmethod
    def _all_text(node):return ''.join((x.text or '') for x in node.iter() if x.tag.endswith('}t')).strip()
    def _docx(self,p):
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'};sections=[];tables=[];paragraphs=[];current=None
        with zipfile.ZipFile(p) as z:
            root=self._zip_xml(z,'word/document.xml')
            body=root.find('w:body',ns)
            for child in ([] if body is None else list(body)):
                if child.tag.endswith('}p'):
                    text=self._all_text(child)
                    if not text:continue
                    style=child.find('./w:pPr/w:pStyle',ns);style_val=style.attrib.get('{%s}val'%ns['w'],'') if style is not None else ''
                    is_list=child.find('./w:pPr/w:numPr',ns) is not None
                    item={'type':'list_item' if is_list else 'paragraph','text':text,'style':style_val or None,'list':is_list}
                    paragraphs.append(item)
                    if style_val.lower().startswith('heading'):
                        current={'heading':text,'paragraphs':[]};sections.append(current)
                    elif current is not None:current['paragraphs'].append(text)
                elif child.tag.endswith('}tbl'):
                    rows=[]
                    for tr in child.findall('.//w:tr',ns):rows.append([self._all_text(tc) for tc in tr.findall('./w:tc',ns)])
                    tables.append({'table':len(tables)+1,'rows':rows})
            meta={}
            if 'docProps/core.xml' in z.namelist():
                c=self._zip_xml(z,'docProps/core.xml')
                for x in c:
                    if x.text:meta[x.tag.split('}')[-1]]=x.text
        return {'type':'docx','sections':sections,'paragraphs':paragraphs[:self.max_units],'tables':tables[:self.max_units]},meta,'stdlib-zip-xml/docx'
    def _pptx(self,p):
        slides=[];notes={}
        with zipfile.ZipFile(p) as z:
            slide_names=sorted((n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)),key=lambda n:int(re.search(r'(\d+)',Path(n).stem).group(1)))[:self.max_units]
            for i,name in enumerate(slide_names,1):
                root=self._zip_xml(z,name);texts=[];tables=[]
                for node in root.iter():
                    if node.tag.endswith('}t') and node.text:texts.append(node.text)
                    if node.tag.endswith('}tbl'):
                        rows=[]
                        for tr in list(node):
                            if tr.tag.endswith('}tr'):rows.append([self._all_text(tc) for tc in list(tr) if tc.tag.endswith('}tc')])
                        if rows:tables.append(rows)
                nname=f'ppt/notesSlides/notesSlide{i}.xml'
                ntext=[]
                if nname in z.namelist():ntext=[x.text for x in self._zip_xml(z,nname).iter() if x.tag.endswith('}t') and x.text]
                slides.append({'slide':i,'title':texts[0] if texts else None,'text':texts,'notes':ntext,'tables':tables})
        return {'type':'pptx','slides':slides},{'slide_count':len(slides)},'stdlib-zip-xml/pptx'
    def _xlsx(self,p):
        ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'};relsns={'r':'http://schemas.openxmlformats.org/package/2006/relationships'};sheets=[]
        with zipfile.ZipFile(p) as z:
            shared=[]
            if 'xl/sharedStrings.xml' in z.namelist():
                sr=self._zip_xml(z,'xl/sharedStrings.xml');shared=[self._all_text(si) for si in list(sr)]
            wb=self._zip_xml(z,'xl/workbook.xml');rels={}
            if 'xl/_rels/workbook.xml.rels' in z.namelist():
                rr=self._zip_xml(z,'xl/_rels/workbook.xml.rels');rels={x.attrib.get('Id'):x.attrib.get('Target') for x in rr}
            for idx,s in enumerate(wb.findall('.//m:sheet',ns),1):
                if idx>self.max_units:break
                name=s.attrib.get('name',f'Sheet{idx}');rid=s.attrib.get('{%s}id'%ns['r']);target=rels.get(rid,f'worksheets/sheet{idx}.xml');target='xl/'+target.lstrip('/') if not target.startswith('xl/') else target
                root=self._zip_xml(z,target);rows=[]
                for row in root.findall('.//m:sheetData/m:row',ns):
                    vals=[]
                    for c in row.findall('./m:c',ns):
                        v=c.find('./m:v',ns);value='' if v is None else (v.text or '')
                        if c.attrib.get('t')=='s' and value.isdigit() and int(value)<len(shared):value=shared[int(value)]
                        vals.append({'ref':c.attrib.get('r'),'value':value[:MAX_CELL_CHARS]})
                    rows.append({'row':int(row.attrib.get('r',len(rows)+1)),'cells':vals})
                    if len(rows)>=self.max_units:break
                headers=[c.get('value','') for c in rows[0]['cells']] if rows else []
                sheets.append({'sheet':name,'headers':headers,'rows':rows})
        return {'type':'xlsx','sheets':sheets},{'sheet_count':len(sheets)},'stdlib-zip-xml/xlsx'
    def _csv(self,p):
        raw=p.read_text(encoding='utf-8-sig',errors='strict');rows=[]
        for i,row in enumerate(csv.reader(io.StringIO(raw)),1):
            if i>self.max_units:break
            rows.append({'row':i,'cells':[str(x)[:MAX_CELL_CHARS] for x in row]})
        headers=list(rows[0]['cells']) if rows else []
        return {'type':'csv','sheets':[{'sheet':'CSV','headers':headers,'rows':rows}]},{'row_count':len(rows)},'stdlib-csv'
    def _text(self,p):
        text=p.read_text(encoding='utf-8',errors='strict')[:self.max_extracted_chars]
        return {'type':'text','sections':[{'section':1,'text':text}]},{'characters':len(text)},'stdlib-text'
    def _structure(self,structured,did):
        chunks=[];units={}
        def add(text,kind,loc,meta=None):
            text=' '.join(str(text).split())
            if not text:return
            for start in range(0,len(text),self.chunk_chars):
                if len(chunks)>=self.max_chunks:return
                part=text[start:start+self.chunk_chars];location=dict(loc);location['char_start']=start;location['char_end']=start+len(part);cid=did+':'+hashlib.sha256(json.dumps(location,sort_keys=True).encode()+part.encode()).hexdigest()[:16];chunks.append(DocumentChunk(cid,part,kind,location,dict(meta or {})))
        typ=structured.get('type')
        if typ=='pdf':
            units['pages']=len(structured['pages'])
            for page in structured['pages']:
                for b in page['blocks']:add(b.get('text',''),'text',{'kind':'page','index':page['page'],'label':f"page {page['page']}"})
        elif typ=='docx':
            units={'sections':len(structured.get('sections',[])),'paragraphs':len(structured.get('paragraphs',[])),'tables':len(structured.get('tables',[]))}
            for i,p in enumerate(structured.get('paragraphs',[]),1):add(p.get('text',''),'paragraph',{'kind':'paragraph','index':i,'label':p.get('style')})
            for t in structured.get('tables',[]):
                for r,row in enumerate(t['rows'],1):add(' | '.join(row),'table_row',{'kind':'table','index':t['table'],'row_start':r,'row_end':r})
        elif typ=='pptx':
            units['slides']=len(structured.get('slides',[]))
            for slide in structured.get('slides',[]):
                add(' '.join(slide.get('text',[])),'slide',{'kind':'slide','index':slide['slide'],'label':slide.get('title')})
                if slide.get('notes'):add(' '.join(slide['notes']),'notes',{'kind':'slide_notes','index':slide['slide']})
        elif typ in {'xlsx','csv'}:
            units['sheets']=len(structured.get('sheets',[]));units['rows']=sum(len(s.get('rows',[])) for s in structured.get('sheets',[]))
            for sheet in structured.get('sheets',[]):
                for row in sheet.get('rows',[]):
                    vals=[c.get('value','') if isinstance(c,dict) else str(c) for c in row.get('cells',[])];add(' | '.join(vals),'sheet_row',{'kind':'sheet','label':sheet['sheet'],'row_start':row['row'],'row_end':row['row']})
        elif typ=='text':
            units['sections']=len(structured.get('sections',[]))
            for section in structured.get('sections',[]):add(section.get('text',''),'text',{'kind':'section','index':section['section']})
        elif typ=='image':
            units['images']=1;add(structured.get('description',''),'image_description',{'kind':'image','index':1,'label':'semantic description'},{'media_type':structured.get('media_type')})
        total=sum(len(c.text) for c in chunks)
        if total>self.max_extracted_chars:
            kept=[];count=0
            for c in chunks:
                if count+len(c.text)>self.max_extracted_chars:break
                kept.append(c);count+=len(c.text)
            chunks=kept
        return chunks,units
    def search(self,query,*,user_id,document_id=None,k=5,for_model=False):
        docs=self.list(user_id=user_id) if document_id is None else [self.get(document_id,user_id=user_id)]
        ready=[d for d in docs if d.status=='READY' and (not for_model or self.allow_external_sensitive or d.classification in {'PUBLIC','PRIVATE'})];candidates=[]
        for d in ready:
            for c in d.chunks:candidates.append({'id':c['chunk_id'],'text':c['text'],'metadata':{'document_id':d.document_id,'filename':d.filename,'classification':d.classification,'content_digest':d.content_digest,'processing_version':d.processing_version,'location':c['location'],'chunk_kind':c['kind']}})
        ranked=self.retriever.retrieve(query,candidates,k=k)
        verified=True
        for x in ranked:
            record=self.get(x['metadata']['document_id'],user_id=user_id);location=x['metadata']['location'];expected=record.document_id+':'+hashlib.sha256(json.dumps(location,sort_keys=True).encode()+x['text'].encode()).hexdigest()[:16]
            if record.content_digest!=x['metadata']['content_digest'] or record.provenance.get('source_digest')!=record.content_digest or expected!=x['id']:verified=False;break
        return {'query':query,'retrieval':'deterministic_bm25_style','items':ranked,'verified':verified}
    def context_items(self,query,*,user_id,k=5):
        result=self.search(query,user_id=user_id,k=k,for_model=True);out=[]
        for item in result['items']:
            m=item['metadata'];out.append(ContextItem('documents',item['id'],item['text'],1.0,1.0,'ALLOW',{'document_id':m['document_id'],'filename':m['filename'],'location':m['location'],'content_digest':m['content_digest'],'processing_version':m['processing_version'],'retrieval':'deterministic_bm25_style'}))
        return out
    def context(self,query,*,user_id,k=5,max_chars=6000):
        items=self.context_items(query,user_id=user_id,k=k);rendered=[];chars=0
        for x in items:
            citation=self.citation(x.provenance);text=f"[{citation}] {x.value}"
            if chars+len(text)>max_chars:break
            rendered.append({'source':'documents','key':x.key,'value':x.value,'provenance':x.provenance,'citation':citation});chars+=len(text)
        return {'source':'document-intelligence','items':rendered,'item_count':len(rendered),'char_count':chars,'rendered':'\n'.join(f"[{x['citation']}] {x['value']}" for x in rendered)}
    @staticmethod
    def citation(provenance):
        loc=provenance.get('location') or {};label=loc.get('label') or (f"{loc.get('kind')} {loc.get('index')}" if loc.get('index') is not None else loc.get('kind'))
        if loc.get('row_start') is not None:label=f"{loc.get('label') or 'sheet'}, row {loc['row_start']}"
        return f"{provenance.get('filename','document')} — {label or 'source'}"
    def evidence(self,query,*,user_id,document_id=None,k=5):
        result=self.search(query,user_id=user_id,document_id=document_id,k=k)
        return [{'statement_type':'document_fact','text':x['text'],'document_id':x['metadata']['document_id'],'source_location':x['metadata']['location'],'content_digest':x['metadata']['content_digest'],'processing_version':x['metadata']['processing_version'],'citation':self.citation(x['metadata'])} for x in result['items']]
    def invoke_search(self,args,*,user_id):
        query=str(args.get('query','')).strip();document_id=args.get('document_id');k=int(args.get('k',5))
        if not query:raise ValueError('document query is required')
        result=self.search(query,user_id=user_id,document_id=document_id,k=k)
        return {'output':result,'verification':{'verified':bool(result.get('verified')),'method':'re-read persisted document digest and bounded deterministic retrieval','document_ids':sorted({x['metadata']['document_id'] for x in result['items']})}}

    def attach(self,document_id,*,user_id,target_type,target_id):
        if target_type not in {'goal','project','task','research','experiment','artifact'}:raise ValueError('unsupported document link target')
        r=self.get(document_id,user_id=user_id);link={'type':target_type,'id':str(target_id)}
        if link not in r.links:r.links.append(link);r.updated_at=self._now();self._save(r)
        return r
    def recover(self,document_id,*,user_id):
        r=self.get(document_id,user_id=user_id)
        if r.status in {'RECEIVED','VALIDATING','EXTRACTING','STRUCTURING'}:
            r.status='FAILED';r.failure={'category':'RECOVERY_REQUIRED','reason':'local synchronous extraction was interrupted; reingest the same source digest'};r.updated_at=self._now();self._save(r)
        return r

    def understanding_status(self,document_id,*,user_id,capability='reasoning'):
        r=self.get(document_id,user_id=user_id)
        if r.status!='READY':return {'status':'BLOCKED','reason':'document is not ready'}
        if r.classification in {'SENSITIVE','HIGHLY_SENSITIVE','DEVICE_CONTROL'} and not self.allow_external_sensitive:return {'status':'BLOCKED','reason':'classification prohibits external model transmission'}
        if self.model_manager is None:return {'status':'SOFTWARE_SUPPORTED','reason':'model manager not attached'}
        route=self.model_manager.route([capability],input_modalities=['text'],output_modalities=['text'])
        return {'status':'AVAILABLE' if route.selected else 'EXTERNALLY_BLOCKED','route':route.to_dict()}

class UnsupportedFormat(ValueError):pass
class ExternalSemanticBlock(RuntimeError):pass
