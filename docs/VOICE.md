# Voice

Voice uses injected STT and TTS adapters and shares the same session/PersonalAgent path as text. Without real STT/TTS providers the runtime reports `EXTERNALLY_BLOCKED` and does not fabricate transcription or speech. Hardware interruption acceptance requires a real microphone/speaker target.
