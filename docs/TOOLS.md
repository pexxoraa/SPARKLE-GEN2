# Tools

Capabilities carry typed identity, version, schemas, authentication, permission, risk, timeout, idempotency, verification, rollback and audit metadata. Execution resolves to an exact registered Gen-1 tool. Unknown tools and shell/raw-command capabilities fail closed; no silent substitution is allowed.

`document_ingest` is an approval-gated Gen-2 capability that accepts only a basename already present inside the private Gen-2 documents root plus an explicit classification; exact arguments are bound into the human approval and model-supplied authority fields are rejected. `document_search` is read-only and accepts a query, optional document ID, and bounded result count; owner identity and chunk/digest provenance are rechecked before the result is considered verified. Neither capability exposes arbitrary host filesystem access.
