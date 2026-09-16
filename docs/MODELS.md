# Models

Gen-2 requests capabilities, not model names. Production planning uses Gen-1 ModelRouter and records provider/model/capability/health/selection reason/request identifiers. Current live model execution is externally blocked because the host exposes no NVIDIA/SPARKLE model credential and Gen-1 reports the configured route unavailable. The planner fails closed with zero tool execution.

Embedding, reranking, image generation and advisory safety-model runtimes have complete provider contracts but remain externally blocked until providers are configured.
