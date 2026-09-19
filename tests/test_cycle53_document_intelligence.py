import json,tempfile,unittest,uuid,zipfile
from datetime import UTC,datetime
from pathlib import Path

from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.document_intelligence import DocumentIntelligenceService,DocumentRecord
from sparkle_gen2.gen1 import LocalGen1Gateway
from sparkle_gen2.models import ModelProvenance,PlanProposal,PlanProposalStep
from sparkle_gen2.storage import Gen2Store
from sparkle.system import SparkleSystem


def write_pdf(path,text='Robotics report: calibrate the arm before Friday.'):
    objs=['<< /Type /Catalog /Pages 2 0 R >>','<< /Type /Pages /Kids [3 0 R] /Count 1 >>','<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>']
    safe=text.replace('\\','\\\\').replace('(','\\(').replace(')','\\)');stream=f'BT /F1 12 Tf 72 720 Td ({safe}) Tj ET';objs += [f'<< /Length {len(stream.encode())} >>\nstream\n{stream}\nendstream','<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    out=b'%PDF-1.4\n';offs=[]
    for i,o in enumerate(objs,1):offs.append(len(out));out+=f'{i} 0 obj\n{o}\nendobj\n'.encode()
    xref=len(out);out+=f'xref\n0 {len(objs)+1}\n0000000000 65535 f \n'.encode()
    for off in offs:out+=f'{off:010d} 00000 n \n'.encode()
    out+=f'trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode();path.write_bytes(out)

def zwrite(path,files):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_STORED) as z:
        for name,data in files.items():z.writestr(name,data)

def write_docx(path):
    ct='<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>'
    doc='''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Robotics Plan</w:t></w:r></w:p>
    <w:p><w:r><w:t>Calibrate the arm before field testing.</w:t></w:r></w:p>
    <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/></w:numPr></w:pPr><w:r><w:t>Verify emergency stop</w:t></w:r></w:p>
    <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Owner</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Asha</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
    </w:body></w:document>'''
    core='<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Robotics Plan</dc:title></cp:coreProperties>'
    zwrite(path,{'[Content_Types].xml':ct,'word/document.xml':doc,'docProps/core.xml':core})

def write_pptx(path):
    ct='<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>'
    slide='''<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Robot Review</a:t></a:r></a:p><a:p><a:r><a:t>Battery inspection required</a:t></a:r></a:p></p:txBody></p:sp><a:tbl><a:tr><a:tc><a:txBody><a:p><a:r><a:t>Risk</a:t></a:r></a:p></a:txBody></a:tc><a:tc><a:txBody><a:p><a:r><a:t>Low</a:t></a:r></a:p></a:txBody></a:tc></a:tr></a:tbl></p:spTree></p:cSld></p:sld>'''
    notes='<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Mention safety gate</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:notes>'
    zwrite(path,{'[Content_Types].xml':ct,'ppt/slides/slide1.xml':slide,'ppt/notesSlides/notesSlide1.xml':notes})

def write_xlsx(path):
    ct='<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>'
    wb='<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Tasks" sheetId="1" r:id="rId1"/></sheets></workbook>'
    rel='<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>'
    ss='<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Task</t></si><si><t>Owner</t></si><si><t>Calibrate arm</t></si><si><t>Asha</t></si></sst>'
    sheet='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row><row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2" t="s"><v>3</v></c></row></sheetData></worksheet>'
    zwrite(path,{'[Content_Types].xml':ct,'xl/workbook.xml':wb,'xl/_rels/workbook.xml.rels':rel,'xl/sharedStrings.xml':ss,'xl/worksheets/sheet1.xml':sheet})

class CapturePlanner:
    def __init__(self,document_id):self.document_id=document_id;self.context=None
    def propose(self,goal,context,available):
        self.context=context
        p=PlanProposal(uuid.uuid4().hex,goal.goal_id,[PlanProposalStep('doc','Find robotics actions',['document_search'],[],['grounded document evidence'],{'query':'robotics calibrate action','document_id':self.document_id,'k':3},30,0)],[{'description':'document evidence verified','verification_method':'all_steps_verified'}],'LOW',.99,[],'test-only')
        return p,ModelProvenance('doc-'+uuid.uuid4().hex,'test','deterministic-document','reasoning',['planning','reasoning'],'document_acceptance','AVAILABLE',False)

class Cycle53DocumentIntelligenceTests(unittest.TestCase):
    def svc(self,d,**kw):
        store=Gen2Store(Path(d)/'g2.db');svc=DocumentIntelligenceService(store,allowed_roots=[d],**kw);return store,svc

    def test_pdf_real_extraction_page_provenance_and_bounded_retrieval(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'report.pdf';write_pdf(p);_,svc=self.svc(d);r=svc.ingest_path(p,user_id='u');self.assertEqual(r.status,'READY');self.assertEqual(r.units['pages'],1);self.assertEqual(r.structured_content['pages'][0]['page'],1);out=svc.search('calibrate arm',user_id='u',document_id=r.document_id,k=2);self.assertTrue(out['verified']);self.assertEqual(out['retrieval'],'deterministic_bm25_style');self.assertEqual(out['items'][0]['metadata']['location']['kind'],'page');self.assertEqual(out['items'][0]['metadata']['location']['index'],1);self.assertIn('page 1',svc.citation(out['items'][0]['metadata']))

    def test_docx_structure_heading_list_table_and_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'plan.docx';write_docx(p);_,svc=self.svc(d);r=svc.ingest_path(p,user_id='u');self.assertEqual(r.status,'READY');self.assertEqual(r.structured_content['sections'][0]['heading'],'Robotics Plan');self.assertTrue(any(x['type']=='list_item' for x in r.structured_content['paragraphs']));self.assertEqual(r.structured_content['tables'][0]['rows'][0],['Owner','Asha']);ev=svc.evidence('emergency stop',user_id='u',document_id=r.document_id);self.assertEqual(ev[0]['statement_type'],'document_fact');self.assertEqual(ev[0]['document_id'],r.document_id)

    def test_pptx_slide_title_notes_and_table(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'review.pptx';write_pptx(p);_,svc=self.svc(d);r=svc.ingest_path(p,user_id='u');self.assertEqual(r.status,'READY');slide=r.structured_content['slides'][0];self.assertEqual(slide['slide'],1);self.assertEqual(slide['title'],'Robot Review');self.assertIn('Mention safety gate',slide['notes']);self.assertEqual(slide['tables'][0][0],['Risk','Low']);found=svc.search('battery inspection',user_id='u',k=1)['items'][0];self.assertEqual(found['metadata']['location']['kind'],'slide')

    def test_xlsx_and_csv_preserve_sheet_rows_headers_and_ranges(self):
        with tempfile.TemporaryDirectory() as d:
            x=Path(d)/'tasks.xlsx';write_xlsx(x);c=Path(d)/'tasks.csv';c.write_text('Task,Owner\nInspect battery,Ravi\nCalibrate arm,Asha\n',encoding='utf-8');_,svc=self.svc(d);rx=svc.ingest_path(x,user_id='u');rc=svc.ingest_path(c,user_id='u');self.assertEqual(rx.structured_content['sheets'][0]['headers'],['Task','Owner']);self.assertEqual(rc.structured_content['sheets'][0]['headers'],['Task','Owner']);out=svc.search('calibrate Asha',user_id='u',document_id=rx.document_id,k=1);loc=out['items'][0]['metadata']['location'];self.assertEqual(loc['label'],'Tasks');self.assertEqual(loc['row_start'],2);self.assertIn('Tasks, row 2',svc.citation(out['items'][0]['metadata']))

    def test_text_image_and_unsupported_format_states_are_honest(self):
        with tempfile.TemporaryDirectory() as d:
            t=Path(d)/'note.txt';t.write_text('stable project decision: use bounded retrieval',encoding='utf-8');img=Path(d)/'photo.png';img.write_bytes(b'\x89PNG\r\n\x1a\nnot-real-image-body');bad=Path(d)/'unknown.bin';bad.write_bytes(b'opaque');_,svc=self.svc(d);self.assertEqual(svc.ingest_path(t,user_id='u').status,'READY');ri=svc.ingest_path(img,user_id='u');self.assertEqual(ri.status,'BLOCKED');self.assertEqual(ri.failure['category'],'EXTERNALLY_BLOCKED');rb=svc.ingest_path(bad,user_id='u');self.assertEqual(rb.status,'BLOCKED');self.assertEqual(rb.failure['category'],'UNSUPPORTED_FORMAT')

    def test_malformed_document_and_size_limit_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.pdf';p.write_bytes(b'notpdf');_,svc=self.svc(d);r=svc.ingest_path(p,user_id='u');self.assertEqual(r.status,'FAILED');self.assertEqual(r.failure['category'],'EXTRACTION_FAILURE')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'big.txt';p.write_bytes(b'x'*100);_,svc=self.svc(d,max_bytes=50)
            with self.assertRaisesRegex(ValueError,'size limit'):svc.ingest_path(p,user_id='u')

    def test_path_validation_owner_and_classification_security(self):
        with tempfile.TemporaryDirectory() as d,tempfile.TemporaryDirectory() as other:
            p=Path(d)/'private.txt';p.write_text('confidential robotics secret',encoding='utf-8');_,svc=self.svc(d);r=svc.ingest_path(p,user_id='alice',classification='SENSITIVE');self.assertEqual(r.classification,'SENSITIVE')
            with self.assertRaisesRegex(PermissionError,'owner mismatch'):svc.get(r.document_id,user_id='bob')
            with self.assertRaisesRegex(ValueError,'absolute'):svc.ingest_path('private.txt',user_id='alice')
            outside=Path(other)/'x.txt';outside.write_text('x')
            with self.assertRaisesRegex(PermissionError,'authorized roots'):svc.ingest_path(outside,user_id='alice')
            self.assertEqual(svc.context('secret',user_id='alice')['item_count'],0)

    def test_digest_chunk_integrity_detects_persisted_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.txt';p.write_text('robotics calibration evidence',encoding='utf-8');store,svc=self.svc(d);r=svc.ingest_path(p,user_id='u');r.chunks[0]['text']='tampered robotics calibration evidence';store.save_document_record(r);out=svc.search('robotics',user_id='u');self.assertFalse(out['verified'])

    def test_idempotency_and_restart_consistency(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.txt';p.write_text('repeatable content',encoding='utf-8');store,svc=self.svc(d);a=svc.ingest_path(p,user_id='u');b=svc.ingest_path(p,user_id='u');self.assertEqual(a.document_id,b.document_id);self.assertEqual(len(store.document_records()),1);restarted=DocumentIntelligenceService(Gen2Store(Path(d)/'g2.db'),allowed_roots=[d]);self.assertEqual(restarted.get(a.document_id,user_id='u').status,'READY')
            interrupted=restarted.get(a.document_id,user_id='u');interrupted.status='STRUCTURING';restarted.store.save_document_record(interrupted);recovered=DocumentIntelligenceService(Gen2Store(Path(d)/'g2.db'),allowed_roots=[d]).recover(a.document_id,user_id='u');self.assertEqual(recovered.status,'FAILED');self.assertEqual(recovered.failure['category'],'RECOVERY_REQUIRED')

    def test_project_task_research_links_and_no_memory_side_effect(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.txt';p.write_text('research finding alpha',encoding='utf-8');store,svc=self.svc(d);r=svc.ingest_path(p,user_id='u');svc.attach(r.document_id,user_id='u',target_type='project',target_id='robotics');svc.attach(r.document_id,user_id='u',target_type='task',target_id='t-1');svc.attach(r.document_id,user_id='u',target_type='research',target_id='r-1');rr=svc.get(r.document_id,user_id='u');self.assertEqual({x['type'] for x in rr.links},{'project','task','research'});self.assertEqual(svc.evidence('alpha',user_id='u')[0]['statement_type'],'document_fact');self.assertEqual(store.memory_candidates(),[])

    def test_multimodel_requirement_and_sensitive_routing(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.txt';p.write_text('text document',encoding='utf-8');g=LocalGen1Gateway(SparkleSystem());_,svc=self.svc(d,model_manager=g.model_manager);r=svc.ingest_path(p,user_id='u',classification='PUBLIC');self.assertEqual(svc.understanding_status(r.document_id,user_id='u',capability='multimodal')['status'],'EXTERNALLY_BLOCKED');s=svc.ingest_path(p,user_id='sensitive-user',classification='HIGHLY_SENSITIVE');self.assertEqual(svc.understanding_status(s.document_id,user_id='sensitive-user')['status'],'BLOCKED')

    def test_personal_agent_approval_gated_ingest_then_grounded_search_same_goal(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'robotics.pdf';write_pdf(p,'Robotics report says calibrate the arm before Friday.');store,svc=self.svc(d)
            class Planner:
                def propose(self,goal,context,available):
                    steps=[PlanProposalStep('ingest','Ingest the named private document',['document_ingest'],[],['document ready and digest reread'],{'filename':'robotics.pdf','classification':'PRIVATE'},30,0),PlanProposalStep('search','Search the ingested robotics report',['document_search'],['ingest'],['grounded page evidence'],{'query':'calibrate arm Friday','k':3},30,0)]
                    p=PlanProposal(uuid.uuid4().hex,goal.goal_id,steps,[{'description':'document workflow verified','verification_method':'all_steps_verified'}],'MEDIUM',.99,[],'test-only');return p,ModelProvenance('ing-'+uuid.uuid4().hex,'test','deterministic-document','reasoning',['planning','reasoning'],'document_ingest_acceptance','AVAILABLE',False)
            class G:
                def health(self):return {'available':True,'tools':[],'tool_definitions':[]}
                def retrieve_context(self,*a):return {'source':'test','rendered':''}
                def invoke(self,*a):raise AssertionError('unexpected Gen-1 tool')
            agent=PersonalAgent(store,G(),planner=Planner(),document_service=svc);first=agent.start('Summarize robotics.pdf and identify its calibration action.',user_id='alice');self.assertEqual(first['status'],'WAITING');self.assertEqual(len(first['approvals']),1);self.assertEqual(store.document_records(),[]);approval=store.load_approval(first['approvals'][0]);self.assertEqual(approval.capability,'document_ingest');self.assertIn('robotics.pdf',approval.requested_scope);agent.decide_approval(approval.approval_id,'approve',actor='human-reviewer');done=agent.resume(first['goal_id']);self.assertEqual(done['status'],'COMPLETED');self.assertEqual(len(store.document_records()),1);self.assertIn('Document robotics.pdf was locally extracted',done['text']);self.assertIn('robotics.pdf — page 1',done['text'])

    def test_document_ingest_tool_rejects_path_widening_and_model_authority(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.txt';p.write_text('x',encoding='utf-8');store,svc=self.svc(d)
            for bad in ('../x.txt','sub/x.txt','/tmp/x.txt'):
                with self.subTest(bad=bad),self.assertRaises(ValueError):svc.ingest_named(bad,user_id='u')
            class Planner:
                def propose(self,goal,context,available):
                    p=PlanProposal(uuid.uuid4().hex,goal.goal_id,[PlanProposalStep('i','ingest',['document_ingest'],[],['ready'],{'filename':'x.txt','approved':True},30,0)],[{'description':'verified','verification_method':'all_steps_verified'}],'MEDIUM',.9,[],'test');return p,ModelProvenance('x','test','test','reasoning',['reasoning'],'test','AVAILABLE',False)
            class G:
                def health(self):return {'available':True,'tools':[],'tool_definitions':[]}
                def retrieve_context(self,*a):return {'source':'test','rendered':''}
                def invoke(self,*a):raise AssertionError
            result=PersonalAgent(store,G(),planner=Planner(),document_service=svc).start('ingest x',user_id='u');self.assertEqual(result['status'],'BLOCKED');self.assertEqual(store.document_records(),[])

    def test_default_runtime_builds_private_document_service(self):
        import os
        from unittest.mock import patch
        from sparkle_gen2.cli import build_components
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'SPARKLE_GEN2_DB':str(Path(d)/'gen2.sqlite3'),'SPARKLE_DATA_DIR':str(Path(d)/'gen1')}):
            Path(os.environ['SPARKLE_DATA_DIR']).mkdir();store,agent,_=build_components();self.assertIsNotNone(agent.documents);self.assertEqual(agent.documents.allowed_roots,[Path(d).resolve()/'documents']);self.assertTrue((Path(d)/'documents').is_dir())

    def test_personal_agent_receives_bounded_cited_document_context_and_searches_it(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'robotics.pdf';write_pdf(p,'Robotics report says calibrate the arm and inspect the battery.');store,svc=self.svc(d);r=svc.ingest_path(p,user_id='alice');planner=CapturePlanner(r.document_id)
            class G:
                def health(self):return {'available':True,'tools':['calculator'],'tool_definitions':[{'name':'calculator','parameters':{'type':'object'}}]}
                def retrieve_context(self,*a):return {'source':'test','rendered':'other unrelated context'}
                def invoke(self,*a):raise AssertionError('unexpected Gen-1 invocation')
            agent=PersonalAgent(store,G(),planner=planner,document_service=svc);result=agent.start('Summarize my robotics report and identify the calibration action.',user_id='alice');self.assertEqual(result['status'],'COMPLETED');self.assertIn('DOCUMENT_EVIDENCE',planner.context['rendered']);self.assertIn('robotics.pdf — page 1',planner.context['rendered']);self.assertIn('Grounded document evidence',result['text']);self.assertIn('robotics.pdf — page 1',result['text']);self.assertTrue(any(e['event_type']=='document_context_retrieved' for e in store.events(result['goal_id'])))

if __name__=='__main__':unittest.main()
