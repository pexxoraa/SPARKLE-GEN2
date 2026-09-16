# Models

SPARKLE Gen-2 retains the provider-neutral Gen-1 model abstraction, but the release product registry contains exactly one enabled AI record: NVIDIA Nemotron 3.5 Lightning (`nvidia/nemotron-3.5-lightning-30b-a3b`). `allow_fallback` is false and Gen-2 rejects any non-NVIDIA, non-Nemotron or fallback routing decision.

Nemotron is the only model permitted for conversation/planning/reasoning/coding/tool-use operations supported by its text interface. Deterministic policy, permissions, approvals, e-stop and independent verification remain authoritative and cannot be overridden by model output.

If neither `NVIDIA_API_KEY` nor the provider-neutral `SPARKLE_LLM_API_KEY` is available, model-backed work enters a recoverable waiting/degraded state and executes no tool. It never switches to another model.

Embedding-specific retrieval and neural reranking are externally blocked because the configured Nemotron text model does not expose those operations. Normal local retrieval uses deterministic lexical/BM25-style ranking, metadata, provenance and structured knowledge traversal; it is not described as embeddings or neural reranking. The configured Nemotron record is text-only, so semantic image/audio/video understanding is also externally blocked.
