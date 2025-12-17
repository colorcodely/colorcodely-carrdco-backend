import os
import logging
import requests
from flask import Flask, request, Response, jsonify
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

# --------------------------------------------------
# Logging
# --------------------------------------------------
logging.basicConfig(level=logging.INFO)

# --------------------------------------------------
# Environment variables (Render)
# --------------------------------------------------
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM_NUMBER = os.environ["TWILIO_FROM_NUMBER"]
TWILIO_TO_NUMBER = os.environ["TWILIO_TO_NUMBER"]

GH_ACTIONS_TOKEN = os.environ.get("GH_ACTIONS_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")  # format: owner/repo

APP_BASE_URL = os.environ.get(
    "APP_BASE_URL",
    "https://colorcodely-carrdco-backend.onrender.com"
)

# --------------------------------------------------
# Clients
# --------------------------------------------------
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
app = Flask(__name__)

# --------------------------------------------------
# Health check
# --------------------------------------------------
@app.route("/", methods=["GET", "HEAD"])
def health():
    return "OK", 200

# --------------------------------------------------
# Trigger outbound call
# --------------------------------------------------
@app.route("/daily-call", methods=["POST"])
def daily_call():
    call = twilio_client.calls.create(
        to=TWILIO_TO_NUMBER,
        from_=TWILIO_FROM_NUMBER,
        url=f"{APP_BASE_URL}/twiml/record",
        method="POST",
        timeout=55,
        trim="trim-silence"
    )

    logging.info(f"Call started: {call.sid}")
    return jsonify({"call_sid": call.sid}), 200

# --------------------------------------------------
# TwiML: record ONCE, then hang up
# --------------------------------------------------
@app.route("/twiml/record", methods=["POST"])
def twiml_record():
    vr = VoiceResponse()

    vr.record(
        maxLength=120,
        playBeep=False,
        trim="trim-silence",
        recordingStatusCallback=f"{APP_BASE_URL}/twilio/recording-complete",
        recordingStatusCallbackMethod="POST"
    )

    vr.hangup()
    return Response(str(vr), mimetype="text/xml")

# --------------------------------------------------
# Recording complete → GitHub dispatch
# --------------------------------------------------
@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    call_sid = request.form.get("CallSid")
    recording_url = request.form.get("RecordingUrl")

    logging.info("Recording completed")
    logging.info(f"Call SID: {call_sid}")
    logging.info(f"Recording URL: {recording_url}")

    if not GH_ACTIONS_TOKEN or not GITHUB_REPO:
        logging.warning("GitHub dispatch not configured — skipping dispatch")
        return "", 200

    dispatch_url = f"https://api.github.com/repos/{GITHUB_REPO}/dispatches"

    headers = {
        "Authorization": f"Bearer {GH_ACTIONS_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    payload = {
        "event_type": "twilio-recording",
        "client_payload": {
            "call_sid": call_sid,
            "recording_url": recording_url
        }
    }

    response = requests.post(
        dispatch_url,
        headers=headers,
        json=payload,
        timeout=10
    )

    logging.info(f"GitHub dispatch response: {response.status_code}")

    return "", 200
