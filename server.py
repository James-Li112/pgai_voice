"""FastAPI server that receives Twilio's Media Streams WebSocket and runs the
same OpenAI Realtime pipeline used by voice_bot.py, over the phone instead of
a local mic. Also receives Twilio's recording-status webhook and downloads
the finished call recording.

Run this (exposed via ngrok as PUBLIC_URL) before placing a call with
first_call.py -- Twilio connects here the moment the call is answered.
"""

import json
import os
import time
from pathlib import Path

import aiohttp
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket

from persona import DEFAULT_SCENARIO, SCENARIOS
from pipecat.frames.frames import InterimTranscriptionFrame, TranscriptionFrame
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    AssistantTurnStoppedMessage,
    LLMContextAggregatorPair,
    UserTurnMessageAddedMessage,
)
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.services.openai.realtime.events import (
    AudioConfiguration,
    AudioInput,
    InputAudioNoiseReduction,
    InputAudioTranscription,
    TurnDetection,
    SessionProperties,
)
from pipecat.services.openai.realtime import events as realtime_events
from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

load_dotenv(override=True)

# TEMPORARY DIAGNOSTIC: pipecat doesn't log raw incoming Realtime API events
# anywhere, and its receive loop silently drops event types it doesn't
# explicitly dispatch (e.g. conversation.item.input_audio_transcription.failed
# has no handler at all). Patch the parser so every event type is visible
# while we track down why no transcription is showing up. Remove once fixed.
_original_parse_server_event = realtime_events.parse_server_event


def _debug_parse_server_event(message):
    evt = _original_parse_server_event(message)
    if evt.type != "response.output_audio.delta":  # far too noisy to print
        print(f"[debug] realtime event: {evt.type}")
        if evt.type == "error" or "failed" in evt.type:
            print(f"[debug]   details: {evt}")
    return evt


realtime_events.parse_server_event = _debug_parse_server_event

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]

# Twilio's wire format is fixed at 8kHz mu-law -- TwilioFrameSerializer handles
# that conversion on its own (via its separate twilio_sample_rate default).
# This is the *pipeline's* internal PCM rate, which must match what OpenAI
# Realtime expects (a fixed 24kHz): OpenAIRealtimeLLMService sends frame.audio
# straight through with no resampling of its own, so if this doesn't match,
# audio arrives at the wrong speed/pitch and its VAD never recognizes it as
# speech -- silently, with no errors, which is exactly what caused the two
# dead-silent calls this was debugged from.
PIPELINE_SAMPLE_RATE = 24000

TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"
RECORDINGS_DIR = Path(__file__).parent / "recordings"

app = FastAPI()


class DebugTranscriptionObserver(BaseObserver):
    """Temporary diagnostic: logs every transcription frame, from whichever
    processor pushes it, regardless of final/interim status. Unlike
    on_user_turn_message_added, this shows us raw transcription events even
    when they're empty or never reach the aggregator as a real user turn."""

    async def on_push_frame(self, data: FramePushed):
        frame = data.frame
        if isinstance(frame, TranscriptionFrame):
            print(f"[debug] TranscriptionFrame (final): {frame.text!r}")
        elif isinstance(frame, InterimTranscriptionFrame):
            print(f"[debug] InterimTranscriptionFrame: {frame.text!r}")


def open_transcript_file(scenario: str, call_sid: str):
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    path = TRANSCRIPTS_DIR / f"call-{call_sid}-{scenario}.txt"
    return open(path, "a", encoding="utf-8")


@app.websocket("/audio")
async def audio_endpoint(websocket: WebSocket):
    call_start = time.monotonic()
    await websocket.accept()

    # Twilio sends two JSON text frames before any audio:
    #   1. {"event": "connected", ...}
    #   2. {"event": "start", "start": {"streamSid", "callSid", "customParameters"}}
    # streamSid/callSid are required to construct the serializer, so these two
    # are read directly off the socket; FastAPIWebsocketTransport takes over
    # for everything after (the "media" events).
    messages = websocket.iter_text()
    await messages.__anext__()  # "connected", nothing to read from it
    start_message = json.loads(await messages.__anext__())
    start = start_message["start"]
    stream_sid = start["streamSid"]
    call_sid = start["callSid"]
    scenario = start.get("customParameters", {}).get("scenario", DEFAULT_SCENARIO)
    system_instruction = SCENARIOS[scenario]

    serializer = TwilioFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        account_sid=TWILIO_ACCOUNT_SID,
        auth_token=TWILIO_AUTH_TOKEN,
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=serializer,
        ),
    )

    llm = OpenAIRealtimeLLMService(
        api_key=os.environ["OPENAI_API_KEY"],
        settings=OpenAIRealtimeLLMService.Settings(
            system_instruction=system_instruction,
            session_properties=SessionProperties(
                audio=AudioConfiguration(
                    input=AudioInput(
                        transcription=InputAudioTranscription(),
                        # Semantic VAD (even at low eagerness) reads the clean
                        # sentence-final pauses inside a scripted IVR/monitoring
                        # announcement as the far end finishing its turn. Plain
                        # silence-duration VAD with a generous window is more
                        # robust here: it only cares about literal silence, not
                        # whether a sentence sounds "complete".
                        turn_detection=TurnDetection(
                            threshold=0.5, prefix_padding_ms=300, silence_duration_ms=900
                        ),
                        noise_reduction=InputAudioNoiseReduction(type="near_field"),
                    )
                ),
            ),
        ),
    )

    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(context)

    transcript_file = open_transcript_file(scenario, call_sid)

    def log_turn(role: str, text: str, note: str = ""):
        elapsed = int(time.monotonic() - call_start)
        timestamp = f"[{elapsed // 60:02d}:{elapsed % 60:02d}]"
        suffix = f"  [{note}]" if note else ""
        line = f"{timestamp} {role}: {text}{suffix}"
        print(line)
        transcript_file.write(line + "\n")
        transcript_file.flush()

    @user_aggregator.event_handler("on_user_turn_message_added")
    async def on_user_turn_message_added(aggregator, message: UserTurnMessageAddedMessage):
        log_turn("user", message.content)

    @assistant_aggregator.event_handler("on_assistant_turn_stopped")
    async def on_assistant_turn_stopped(aggregator, message: AssistantTurnStoppedMessage):
        log_turn("bot", message.content, "interrupted" if message.interrupted else "")

    pipeline = Pipeline(
        [
            transport.input(),
            user_aggregator,
            llm,
            transport.output(),
            assistant_aggregator,
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=PIPELINE_SAMPLE_RATE,
            audio_out_sample_rate=PIPELINE_SAMPLE_RATE,
        ),
        observers=[DebugTranscriptionObserver()],
    )

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        # Without this, nothing tells the pipeline the call actually ended
        # (hangup, or Twilio's time_limit cap) -- it would otherwise sit
        # holding the OpenAI Realtime connection open until the unrelated
        # 300s idle timeout eventually cancels it as a fallback.
        print(f"Call {call_sid} disconnected")
        await task.cancel()

    # handle_sigint=False: this process is a long-running server handling one
    # call at a time, not a standalone script -- uvicorn owns Ctrl+C shutdown.
    runner = PipelineRunner(handle_sigint=False)
    print(f"Call {call_sid} connected -- scenario: {scenario}")
    try:
        await runner.run(task)
    finally:
        transcript_file.close()
        print(f"Call {call_sid} ended")


@app.post("/recording-status")
async def recording_status(request: Request):
    """Twilio posts here when a call's recording finishes; download the MP3."""
    form = await request.form()
    if form.get("RecordingStatus") != "completed":
        return {"ok": True}

    recording_url = form["RecordingUrl"]
    call_sid = form.get("CallSid", "unknown")

    RECORDINGS_DIR.mkdir(exist_ok=True)
    dest = RECORDINGS_DIR / f"{call_sid}.mp3"

    auth = aiohttp.BasicAuth(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{recording_url}.mp3", auth=auth) as response:
            response.raise_for_status()
            dest.write_bytes(await response.read())

    print(f"Saved recording for call {call_sid} -> {dest}")
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
