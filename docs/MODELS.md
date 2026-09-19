# Models

SPARKLE Gen-2 uses the existing Gen-1 `ModelRegistry` through a capability-first Gen-2 `ModelCapabilityManager` / `CapabilityRouter`. The production registry is NVIDIA Nemotron-only and every configured record has `allow_fallback=false`; deterministic policy, permissions, approvals, e-stop, and independent verification remain authoritative over model output.

Current verified production routes are:

- `reasoning`, `planning`, `coding`, `tool_use`, and `general` → NVIDIA Nemotron 3.5 Lightning (`nvidia/nemotron-3.5-lightning-30b-a3b`). Cycle58 exercised a real PersonalAgent goal: live Lightning planning selected the calculator, the tool executed, SPARKLE independently verified `42`, and the goal completed with `fallback=false`.
- `multimodal` and `perception` with image input → NVIDIA Nemotron 3 Nano Omni (`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`). Cycle58 exercised real image inference through `DocumentIntelligenceService`; the grounded result and provider/model/request provenance were persisted.
- `embedding` → NVIDIA Nemotron 3 Embed 1B (`nvidia/nemotron-3-embed-1b`). Cycle58 exercised the real embeddings endpoint through the capability router; vectors were 2048-dimensional and drove `PersistentSemanticIndex` retrieval into bounded Personal Context.
- `reranking` → NVIDIA Llama Nemotron Rerank VL 1B v2 (`nvidia/llama-nemotron-rerank-vl-1b-v2`). Cycle59 exercised the real model-specific NVIDIA retrieval endpoint through `CapabilityRoutedReranker`; bounded embedding candidates were reordered and rerank score/model provenance propagated into Personal Context with `fallback=false`.
- `safety` → NVIDIA Nemotron 3.5 Content Safety (`nvidia/nemotron-3.5-content-safety`). Cycle59 exercised real safe and unsafe advisory classifications. The result is persisted with provider/model/request/reference/timestamp provenance and is explicitly non-authoritative; deterministic SPARKLE policy can use a flagged signal only to tighten review, never to grant permission or weaken an existing deny/approval requirement.

The Gen-1 routing `roles` deliberately keep Omni out of generic `reasoning`; its Gen-2 capability declaration still includes `reasoning` together with `multimodal`/`perception`. This prevents ordinary PersonalAgent planning from silently selecting Omni while allowing Gen-2 compound capability requests such as `[multimodal, reasoning]` to select it.

`NVIDIAEmbeddingAdapter` is registered as a Gen-2 adapter factory inside the existing `ModelRegistry`; no second model registry exists and no Gen-1 source change was required. Query and passage embeddings remain separate operations in semantic retrieval.

If the server-side NVIDIA credential is absent, these model-backed routes fail closed and no alternate provider/model is selected. Credentials are referenced through the existing `SecretResolver` and are never persisted in model configuration or traces.

The production registry now contains a configured VoiceChat model record and semantic `voice` route, but routing remains externally blocked until the NVCF streaming intermediary/protocol transport is verified and the VoiceChat secret reference is resolvable in the runtime. `image_generation` is now configured to NVIDIA FLUX.2 Klein 4B but remains runtime-blocked when neither established NVIDIA secret reference is present. Deterministic lexical/BM25 retrieval remains available independently of embeddings and is not mislabeled as neural retrieval. Physical camera/robot providers remain separate external device boundaries even though semantic image inference is now available.

- `voice` → NVIDIA Nemotron VoiceChat (`nvidia/nemotron-voicechat`), audio/text input and text/audio streaming output, `fallback=false`. Provider/function metadata is configured but hosted streaming inference is not live-accepted; health metadata alone does not make the route healthy.

- `image_generation` → NVIDIA-hosted Black Forest Labs FLUX.2 Klein 4B (`black-forest-labs/flux.2-klein-4b`) via `https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.2-klein-4b`, text input → image output, `fallback=false`. The externally verified provider contract uses only prompt/height/width/samples/seed/steps. Gen-2 validates/decodes the single returned artifact, independently validates JPEG/PNG dimensions/container, persists it in the existing artifact registry, and rereads its SHA-256 before completion. Provider inference is externally verified; current Gen-2 live acceptance is blocked because this process does not resolve the established NVIDIA secret references.
