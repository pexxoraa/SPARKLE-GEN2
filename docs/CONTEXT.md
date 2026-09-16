# Context

`PersonalContextEngine` selects minimal relevant items using relevance, freshness and goal-term overlap. Items denied by permission are excluded. Each selected item retains source and provenance. Gen-1 context rendering is truncated before model planning; entire personal databases are never sent by default.

The production `PersonalAgent` can consume `PersonalContextAssembler`, which merges bounded Gen-1 personal data, authorized calendar/email/files connectors, Gen-2 goals/recent events, typed devices, fresh world state, preferences, and optional persistent semantic retrieval. Missing or externally blocked sources are skipped rather than dumped or fabricated.
