# Tools

Capabilities carry typed identity, version, schemas, authentication, permission, risk, timeout, idempotency, verification, rollback and audit metadata. Execution resolves to an exact registered Gen-1 tool. Unknown tools and shell/raw-command capabilities fail closed; no silent substitution is allowed.

`document_ingest` is an approval-gated Gen-2 capability that accepts only a basename already present inside the private Gen-2 documents root plus an explicit classification; exact arguments are bound into the human approval and model-supplied authority fields are rejected. `document_search` is read-only and accepts a query, optional document ID, and bounded result count; owner identity and chunk/digest provenance are rechecked before the result is considered verified. Neither capability exposes arbitrary host filesystem access.


## Universal protocol and verifier boundary

The authoritative ToolDefinition/Input/Output/Error and metadata contracts live in domain/contracts/tool_protocol.py. ToolInput correlates owner/goal/run/step/tool/arguments; the dispatcher checks that identity before routing. JSON schema validation is bounded and does not echo argument values. Tool-specific routing lives in application/execution/tool_dispatch.py, separate from lifecycle decisions.

Tool success alone is insufficient. Independent adapter observation plus the selected StepVerifier strategy must pass; unsupported semantic/custom verifiers block unless a trusted handler is registered. See [EXECUTION_ENGINE.md](EXECUTION_ENGINE.md).
