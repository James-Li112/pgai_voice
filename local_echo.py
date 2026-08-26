"""Minimal Pipecat pipeline: mic -> VAD -> speaker, no LLM.

Confirms Pipecat + PyAudio + Silero VAD are wired correctly, and lets you
tune VAD sensitivity/silence timing against your own voice before any LLM
cost or latency enters the picture. Speak into the mic and you should hear
yourself echoed back, with start/stop speech events logged.
"""

import asyncio

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    OutputAudioRawFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams

SAMPLE_RATE = 16000

# Tune these against your own mic to get turn-taking feeling right before
# an LLM is in the loop:
#   confidence  - how sure the VAD must be that it's hearing speech
#   start_secs  - speech must persist this long before "started" fires
#   stop_secs   - silence must persist this long before "stopped" fires
VAD_PARAMS = VADParams(confidence=0.6, start_secs=0.2, stop_secs=0.6)


class EchoProcessor(FrameProcessor):
    """Converts mic input frames into speaker output frames, and logs
    VAD speech-start/stop events."""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InputAudioRawFrame):
            await self.push_frame(
                OutputAudioRawFrame(
                    audio=frame.audio,
                    sample_rate=frame.sample_rate,
                    num_channels=frame.num_channels,
                ),
                direction,
            )
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            print(">> speech started")
            await self.push_frame(frame, direction)
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            print("<< speech stopped")
            await self.push_frame(frame, direction)
        else:
            await self.push_frame(frame, direction)


async def main():
    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        )
    )

    vad = VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VAD_PARAMS))

    pipeline = Pipeline(
        [
            transport.input(),
            vad,
            EchoProcessor(),
            transport.output(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=SAMPLE_RATE,
            audio_out_sample_rate=SAMPLE_RATE,
        ),
    )

    runner = PipelineRunner()
    print("Speak into your mic (Ctrl+C to stop)...")
    await runner.run(task)


if __name__ == "__main__":
    asyncio.run(main())
