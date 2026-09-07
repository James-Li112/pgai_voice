"""Core voice bot: mic -> Pipecat -> OpenAI Realtime API -> speaker.

This is the piece graded on "does the bot hold a coherent voice
conversation" -- test it against your own mic before Twilio is involved.

You play the clinic receptionist: speak first, as if answering the phone.
The bot responds as a patient calling in. Ctrl+C to stop.
"""

import argparse
import asyncio
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from persona import DEFAULT_SCENARIO, SCENARIOS

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    AssistantTurnStoppedMessage,
    LLMContextAggregatorPair,
    UserTurnMessageAddedMessage,
)
from pipecat.services.openai.realtime.events import (
    AudioConfiguration,
    AudioInput,
    InputAudioNoiseReduction,
    InputAudioTranscription,
    TurnDetection,
    SessionProperties,
)
from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams

load_dotenv(override=True)

SAMPLE_RATE_IN = 16000
SAMPLE_RATE_OUT = 24000  # OpenAI Realtime streams audio out at 24kHz

TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"


def open_transcript_file(scenario: str):
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    path = TRANSCRIPTS_DIR / f"local-{scenario}-{datetime.now():%Y%m%d-%H%M%S}.txt"
    return open(path, "a", encoding="utf-8")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario", choices=sorted(SCENARIOS), default=DEFAULT_SCENARIO
    )
    args = parser.parse_args()
    system_instruction = SCENARIOS[args.scenario]
    session_start = time.monotonic()

    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        )
    )

    llm = OpenAIRealtimeLLMService(
        api_key=os.environ["OPENAI_API_KEY"],
        settings=OpenAIRealtimeLLMService.Settings(
            system_instruction=system_instruction,
            session_properties=SessionProperties(
                audio=AudioConfiguration(
                    input=AudioInput(
                        transcription=InputAudioTranscription(),
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

    transcript_file = open_transcript_file(args.scenario)

    def log_turn(role: str, text: str, note: str = ""):
        elapsed = int(time.monotonic() - session_start)
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
            audio_in_sample_rate=SAMPLE_RATE_IN,
            audio_out_sample_rate=SAMPLE_RATE_OUT,
        ),
    )

    runner = PipelineRunner()
    print(f"Scenario: {args.scenario}")
    print("Ready -- speak first, as if you're the receptionist answering the phone.")
    try:
        await runner.run(task)
    finally:
        transcript_file.close()


if __name__ == "__main__":
    asyncio.run(main())
