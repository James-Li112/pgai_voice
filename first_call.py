"""Places a single outbound call via Twilio to the assessment test number,
connecting it to server.py's WebSocket via inline TwiML.

server.py must already be running and reachable at PUBLIC_URL (e.g. via
ngrok) before this is run -- Twilio connects to it the moment the call is
answered.
"""

import argparse
import os

from dotenv import load_dotenv
from twilio.rest import Client
from twilio.twiml.voice_response import Connect, Stream, VoiceResponse

from persona import DEFAULT_SCENARIO, SCENARIOS

load_dotenv(override=True)

# Per docs/challenge.md: all test calls must go to this number, and only
# this number.
TEST_NUMBER = "+18054398008"

MAX_CALL_SECONDS = 240  # hard cap; Twilio force-hangs-up the call at this point


def build_twiml(public_url: str, scenario: str) -> str:
    response = VoiceResponse()
    connect = Connect()
    stream = Stream(url=f"wss://{public_url}/audio")
    stream.parameter(name="scenario", value=scenario)
    connect.append(stream)
    response.append(connect)
    return str(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default=DEFAULT_SCENARIO)
    args = parser.parse_args()

    to_number = TEST_NUMBER
    assert to_number == TEST_NUMBER, "Refusing to call any number other than the test line."

    account_sid = os.environ["TWILIO_ACCOUNT_SID"]
    auth_token = os.environ["TWILIO_AUTH_TOKEN"]
    from_number = os.environ["TWILIO_PHONE_NUMBER"]
    public_url = os.environ["PUBLIC_URL"]

    client = Client(account_sid, auth_token)

    call = client.calls.create(
        to=to_number,
        from_=from_number,
        twiml=build_twiml(public_url, args.scenario),
        time_limit=MAX_CALL_SECONDS,
        record=True,
        recording_status_callback=f"https://{public_url}/recording-status",
        recording_status_callback_event=["completed"],
        recording_status_callback_method="POST",
    )

    print(f"Call placed: sid={call.sid} to={to_number} scenario={args.scenario}")


if __name__ == "__main__":
    main()
