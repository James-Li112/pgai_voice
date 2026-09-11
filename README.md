# Voice Bot — Pretty Good AI Assessment

An automated caller that dials Pretty Good AI's test line, role-plays as a patient
(scheduling, rescheduling, refills, questions, and several edge cases), and logs a
timestamped transcript of the call. See [docs/architecture.md](docs/architecture.md)
for how it's built and why, and [docs/bug-report.md](docs/bug-report.md) for issues
found in the target agent.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill in `.env`:

- `OPENAI_API_KEY` — needs Realtime API access.
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` — from the
  [Twilio console](https://console.twilio.com); the phone number is the one placing
  the call.
- `PUBLIC_URL` — the public hostname `server.py` is reachable at (see below), no
  scheme, e.g. `abc123.ngrok-free.app`.

## Try it against your own mic first (no telephony, no Twilio cost)

```powershell
python voice_bot.py --scenario schedule
```

You play the clinic receptionist (speak first); the bot responds as the patient.
Useful for tuning turn-taking/pacing before spending a real call on it. Only needs
`OPENAI_API_KEY`.

## Placing a real call

Three things need to be running: a tunnel exposing `server.py` to the internet,
`server.py` itself, and then the script that places the call.

```powershell
# terminal 1
ngrok http 8080
# copy the https URL it prints (minus the scheme) into PUBLIC_URL in .env

# terminal 2
python server.py

# terminal 3
python first_call.py --scenario schedule
```

`server.py` must already be running before `first_call.py` is run — Twilio connects
to it the instant the call is answered. Restart `server.py` after any code change
before placing another call (it's a long-running process; Python won't pick up
edits on its own).

Each call writes a timestamped transcript to `transcripts/call-<call_sid>-<scenario>.txt`
and downloads the recording to `recordings/<call_sid>.mp3` once Twilio finishes
processing it.

## Scenarios

`--scenario` accepts any key in `persona.py`'s `SCENARIOS` dict: `schedule`,
`schedule_casual`, `schedule_direct`, `reschedule`, `refill`, `questions`,
`vague_caller`, `weekend_request`, `topic_switch`, `interrupts_agent`,
`off_scope_medical`. Defaults to `schedule` if omitted.

## Test number

All calls go to the fixed test line defined in `first_call.py` (`TEST_NUMBER`) —
never a different number.
