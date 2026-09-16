# Browser and Computer Interaction

Gen-2 consumes Gen-1's supported `InteractionService` session boundary directly. Browser sessions require explicit allowed hosts and revision-checked persisted history; computer sessions require explicit allowed action kinds. Gen-2 never registers unrestricted browser/computer control as a model tool.

The configured safe HTTPS browser is live verified through Gen-2 -> Gen-1 against `https://example.com/` with HTTP 200 and persisted-history verification. Gen-1 reports computer control externally unconfigured, so GUI live execution remains blocked while its software adapter/harness is complete.
