# Document Intelligence

Gen-2 document intelligence is a local-first structured extraction and evidence pipeline:

```text
source file
→ path/size/type validation
→ content SHA-256
→ format-specific extraction
→ canonical structure
→ provenance-preserving chunks
→ bounded deterministic retrieval
→ PersonalAgent context / document_search
```

Binary source files are not copied into a second document artifact store. Gen-2 persists the structured record, digest, processing version, classification, chunks, provenance, and links to goals/projects/tasks/research/experiments/artifacts. The default runtime only accepts files inside its private `${Gen2 DB parent}/documents` root. `PersonalAgent` may invoke approval-gated `document_ingest` using only a basename from that root; the approval binds the exact user/goal/tool/filename/classification scope. Arbitrary host paths and model-supplied approval fields are rejected.

## Supported formats

- PDF: local `pdfinfo` + `pdftotext`; page-level provenance. Text-only PDFs are supported. Image-only/scanned PDFs with no extractable text are `EXTERNALLY_BLOCKED` for OCR/vision.
- DOCX: local ZIP/XML extraction of headings, paragraphs, list items, tables, and core metadata.
- PPTX: local ZIP/XML extraction of slide number, title/text, notes when present, and tables.
- XLSX: local ZIP/XML extraction of workbook sheets, headers, rows, cell references/values.
- CSV: local structured row/header extraction.
- plain text: local bounded text extraction.
- images: PNG/JPEG/GIF semantic understanding is capability-routed to the configured NVIDIA Nemotron Omni model for authorized PUBLIC/PRIVATE local files; the grounded description is structured/chunked with model provenance. Other image media remain explicitly blocked when the configured adapter cannot serialize them.

Unsupported formats are persisted as `BLOCKED/UNSUPPORTED_FORMAT`; malformed supported documents become `FAILED`. Processing states are `RECEIVED`, `VALIDATING`, `EXTRACTING`, `STRUCTURING`, `READY`, `FAILED`, and `BLOCKED`.

## Provenance and retrieval

Every chunk retains `document_id`, filename, source location (page/slide/sheet/row/paragraph), original content digest, processing version, and chunk identity. Chunk identity is deterministic from document identity + source location + extracted text. Document-local `document_search` remains deterministic BM25-style lexical retrieval and is labeled as such. Separately, the Gen-2 persistent semantic index can use the capability-routed Nemotron Embed 1B provider for Personal Context; neural reranking remains unconfigured.

PersonalAgent receives at most a bounded set of matching chunks rather than a whole document dump. `document_search` is read-only and independently rechecks persisted digest/chunk identity before its result is accepted. Downstream research evidence is labeled `document_fact`; interpretation/inference remains separate.

## Privacy and models

Document classification is one of `PUBLIC`, `PRIVATE`, `SENSITIVE`, `HIGHLY_SENSITIVE`, or `DEVICE_CONTROL`. Local extraction is model-free. By default, SENSITIVE/HIGHLY_SENSITIVE/DEVICE_CONTROL content is excluded from external-model context. PUBLIC/PRIVATE text evidence may enter the normal capability-routed reasoning path. Semantic image understanding requires the `multimodal` + `reasoning` capabilities and currently routes to verified Nemotron Omni for PUBLIC/PRIVATE content. SENSITIVE/HIGHLY_SENSITIVE/DEVICE_CONTROL content remains blocked from external transmission by default; absence of an eligible provider also fails closed.

Document ingestion does not create personal memory. Durable personal memory can only arise later through the existing completion-memory candidate/review/approval lifecycle.

## Restart and idempotency

Processing identity is deterministic from owner + source SHA-256 + processing version. Reingesting identical content for the same owner/version returns the same document identity rather than creating duplicate records. READY records survive restart. If a process dies while local synchronous extraction is in an intermediate state, recovery marks it `FAILED/RECOVERY_REQUIRED`; it does not pretend mid-parser resumability.
