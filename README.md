PGAI Voice Bot — Automated Patient Simulator

An automated voice bot that places outbound calls to Pretty Good AI's test line, role-plays as a patient across a range of realistic scenarios, and records and transcribes both sides of each conversation for analysis.

Built with Twilio (telephony), Pipecat (pipeline and media-stream plumbing), and the OpenAI Realtime API (speech-to-speech). See docs/architecture.md for design decisions and tradeoffs, and bug-report.md for issues found in the agent under test.

Requirements
Python 3.13
A Twilio account with a voice-capable US number and an approved compliance profile
An OpenAI API key with credit (the Realtime API is not covered by any free tier)
ngrok to expose the local server to Twilio
Setup
bash
git clone https://github.com/YOURNAME/pgai-voicebot.git
cd pgai-voicebot

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1

pip install -r requirements.txt

Copy .env.example to .env and fill in your own values:

TWILIO_ACCOUNT_SID=      # console.twilio.com, starts with AC
TWILIO_AUTH_TOKEN=       # primary auth token, same page
TWILIO_PHONE_NUMBER=     # your Twilio number, E.164 format e.g. +16035551234
OPENAI_API_KEY=          # platform.openai.com
PUBLIC_URL=              # ngrok hostname, no scheme e.g. abc123.ngrok-free.dev

Nothing else needs configuring. The destination number is a constant in the source and is never read from the environment, so a misconfigured .env cannot cause a call to the wrong line.

Running a call

Twilio opens a WebSocket back to this machine the moment the call is answered, so the server and the tunnel both have to be up first.

Terminal 1 — server

bash
python server.py

Wait for Application startup complete. It listens on port 8080.

Terminal 2 — tunnel

bash
ngrok http 8080

Confirm the forwarding hostname matches PUBLIC_URL in .env. If it changed, update .env and restart the server, which reads it at boot.

Terminal 3 — place the call

bash
python first_call.py --scenario schedule

That single command runs an entire call end to end: it dials the test line, streams audio in both directions through the Realtime pipeline, logs the transcript turn by turn, and downloads the recording when Twilio's webhook fires.

Omit --scenario to use the default (schedule).

Testing without telephony

voice_bot.py runs the same pipeline against your laptop microphone and speakers instead of a phone line. You play the receptionist; the bot responds as the patient.

bash
python voice_bot.py --scenario reschedule

This is the fastest way to iterate on conversational behavior — it costs nothing in telephony charges and gives instant feedback on turn-taking and pacing. Use headphones, or the speaker output feeds back into the mic and the bot interrupts itself.

Scenarios

Personas live in persona.py as system instructions: a shared base defining how a real caller behaves on the phone, plus a per-scenario goal, personality, and built-in ambiguity.

Scenario	What it tests
schedule	Simple appointment booking, returning patient
schedule_casual	Booking with vague, non-committal timing
schedule_direct	Blunt caller with a narrow time window; asks the agent to read the name back
reschedule	Moving an existing appointment the caller can't recall the details of
refill	Blood-pressure medication refill, pharmacy and identity verification
questions	Office hours, location, and insurance coverage as a prospective patient
weekend_request	Booking on a Saturday or Sunday
topic_switch	Abandons scheduling mid-call and switches to a refill request
interrupts_agent	Deliberate barge-in, twice per call
off_scope_medical	Asks the agent directly for medical advice
vague_caller	Opens with an unclear request and only clarifies when pressed

Adding a scenario means adding one entry to SCENARIOS; no other code changes.

Output
Path	Contents
transcripts/call-<CallSid>-<scenario>.txt	Turn-by-turn transcript with elapsed timestamps, speaker-labelled, interruptions marked
recordings/<CallSid>.mp3	Full call audio, downloaded via Twilio's recording webhook
transcripts/local-<scenario>-<timestamp>.txt	Transcripts from local microphone runs

Transcripts come from the Realtime API's own transcription events rather than a separate pass, so they're written live as the call proceeds.

Layout
server.py        FastAPI app: Media Streams WebSocket + recording webhook
first_call.py    Places an outbound call and connects it to the server
voice_bot.py     Same pipeline against a local mic, for testing
persona.py       Patient personas as system instructions
docs/            Architecture doc and product notes
transcripts/     Per-call transcripts
recordings/      Per-call MP3s
Notes
All calls go to +1-805-439-8008 only. The number is a module-level constant with an assertion before dialing.
Calls have a hard duration cap. There are no retries and no concurrency — one call at a time.
.env is gitignored. .env.example documents every variable the project reads.
