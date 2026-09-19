# Memory

Gen-2 never treats goal completion as permission to create durable memory. After a goal is deterministically `COMPLETED`, `PersonalAgent` runs a bounded completion-memory analysis. It may produce zero or more `MemoryCandidate` records; ordinary transient results, execution metadata, unverified claims, and secret/token/credential-bearing text are intentionally ignored. The default analyzer is deterministic and conservative, so Nemotron availability is not required for this safety boundary.

A candidate is review metadata, not authoritative memory. It records a deterministic candidate ID, goal/task/trace provenance, candidate value and category, reason/source, supporting verified evidence, confidence, privacy classification, creation time, and review state. Candidate IDs derive from the goal, category, and normalized value, so observing the same completed goal repeatedly does not create duplicate proposals.

The lifecycle is:

`verified completion -> PROPOSED candidate -> explicit human approve/reject -> Gen-1 memory_write proposal -> Gen-1 review -> reconciliation -> PERSISTED or REVIEW_REJECTED`

Explicit Gen-2 approval does not itself create memory. Approval only submits the candidate through the existing Gen-1 `memory_write` boundary, which must return a verified pending review proposal. Model/system identities cannot approve candidates. If Gen-1 review approves, reconciliation records the authoritative Gen-1 `memory_id`; rejection never creates durable memory.

Candidates persist in the Gen-2 store across restart while Gen-1 remains the only authoritative durable memory store. The retained `memory_id -> candidate -> goal/task/trace/evidence` link preserves provenance without duplicating Gen-1 memory contents.
