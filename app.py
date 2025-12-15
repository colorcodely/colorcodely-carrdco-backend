import os
import logging
import requests
from flask import Flask, request, Response, jsonify
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Record

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ======================
# REQUIRED ENV VARS
# ======================
REQUIRED_ENV_VARS = [
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM_NUMBER",
    "TWILIO_TO_NUMBER",
    "GITHUB_REPO",
    "GH_ACTIONS_TOKEN",
]

missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
if missing:
    raise RuntimeError(f"Missing required env vars: {missing}")

# ======================
# CLIENTS
# ======================
twilio_client = Client(
    os.environ["TWILIO_ACCOUNT_SID"],
    os.environ["TWILIO_AUTH_TOKEN"],
)

GITHUB_DISPATCH_URL = f"https://api.github.com/repos/{os.environ['GITHUB_REPO']}/dispatches"
GITHUB_HEADERS = {
    "Authorization": f"token {os.environ['GH_ACTIONS_TOKEN']}",
    "Accept": "application/vnd.github+json",
    # Not strictly required, but helpful / more standard:
    "User-Agent": "colorcodely-dispatcher",
}

# IMPORTANT: this MUST match your workflow `types: [...]`
DISPATCH_EVENT_TYPE = "twilio-recording"


# ======================
# HEALTH CHECK
# ======================
@app.route("/", methods=["GET"])
def health():
    return "OK", 200


# ======================
# DAILY CALL TRIGGER
# ======================
@app.route("/daily-call", methods=["POST"])
def daily_call():
    call = twilio_client.calls.create(
        to=os.environ["TWILIO_TO_NUMBER"],
        from_=os.environ["TWILIO_FROM_NUMBER"],
        url=f"{request.host_url}twiml/record",
        method="POST",
        timeout=55,
        trim="trim-silence",
    )

    logging.info(f"Call started: {call.sid}")
    return jsonify({"call_sid": call.sid}), 200


# ======================
# TWIML — RECORD ONCE
# ======================
@app.route("/twiml/record", methods=["POST"])
def twiml_record():
    """
    IMPORTANT:
    - Twilio may hit this endpoint multiple times
    - We must only issue <Record> once
    """
    already_recorded = request.values.get("RecordingSid")

    response = VoiceResponse()

    if not already_recorded:
        response.append(
            Record(
                maxLength=120,
                playBeep=False,
                trim="trim-silence",
                recordingStatusCallback=f"{request.host_url}twilio/recording-complete",
                recordingStatusCallbackMethod="POST",
            )
        )
    else:
        response.hangup()

    return Response(str(response), mimetype="text/xml")


# ======================
# RECORDING COMPLETE
# ======================
@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_url = request.values.get("RecordingUrl")
    call_sid = request.values.get("CallSid")

    if not recording_url or not call_sid:
        logging.error("Missing RecordingUrl or CallSid")
        return "", 400

    logging.info("Recording completed")
    logging.info(f"Call SID: {call_sid}")
    logging.info(f"Recording URL: {recording_url}")

    payload = {
        # MUST match workflow types: [twilio-recording]
        "event_type": DISPATCH_EVENT_TYPE,
        "client_payload": {
            "recording_url": recording_url,
            "call_sid": call_sid,
        },
    }

    try:
        r = requests.post(
            GITHUB_DISPATCH_URL,
            headers=GITHUB_HEADERS,
            json=payload,
            timeout=15,
        )

        # Always log what GitHub said (this is gold for troubleshooting)
        logging.info(f"GitHub dispatch status: {r.status_code}")
        if r.text:
            logging.info(f"GitHub dispatch response: {r.text}")

        if r.status_code >= 300:
            logging.error(f"GitHub dispatch failed: {r.status_code} {r.text}")
        else:
            logging.info("GitHub Actions transcription dispatched")

    except Exception as e:
        logging.exception(f"GitHub dispatch exception: {e}")

    return "", 200


# ======================
# MAIN
# ======================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
