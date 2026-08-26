## Architecture (decided, don't re-litigate)
Twilio outbound call -> Pipecat -> OpenAI Realtime API (speech-to-speech).
Transcripts come from Realtime's transcription events, logged per turn.
ngrok for the public URL. Rationale lives in docs/architecture.md.