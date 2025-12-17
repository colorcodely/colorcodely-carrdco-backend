import os
import logging
from flask import Flask, request, jsonify
from twilio.rest import Client
import requests

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -----------------------------
# Environment Variables
# -----------------------------
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")
TWILIO_TO_NUMBER = os.environ.get("TWILIO_TO_NUMBER")

# Optional GitHub dispatch (safe if unset)
GITHUB_DISPATCH_URL = os.environ.get("GITHUB_DISPATCH_URL")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_EVENT_TYPE = os.environ.get("GITHUB_EVENT_TYPE", "twilio-recording")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# -----------------------------
# Health Check
# -----------------------------
@app.route("/", methods=["GET", "HEAD"])
def health():
    return "OK", 200

# -----------------------------
# Trigger outbound call
# -----------------------------
@app.route("/daily-call", methods=["POST"])
def daily_call():
    if not TWILIO_TO_NUMBER:
        logging.error("TWILIO_TO_NUMBER is not set")
        return jsonify({"error": "TWILIO_TO_NUMBER missing"}), 500

    call = twilio_client.calls.create(
        to=TWILIO_TO_NUMBER,
        from_=TWILIO_FROM_NUMBER,
        url="https://colorcodely-carrdco-backend.onrender.com/twiml/record",
        method="POST",
        timeout=55,
        trim="trim-silence"
    )

    logging.info(f"Call started: {call.sid}")
    return jsonify({"call_sid": call.sid}), 200

# -----------------------------
# TwiML: Record audio
# -----------------------------
@app.route("/twiml/record", methods=["POST"])
def twiml_record():
    return """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Record
        maxLength="120"
        playBeep="false"
        trim="trim-silence"
        recordingStatusCallback="https://colorcodely-carrdco-backend.onrender.com/twilio/recording-complete"
        recordingStatusCallbackMethod="POST"
    />
</Response>""", 200, {"Content-Type": "text/xml"}

# -----------------------------
# Recording complete webhook
# -----------------------------
@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    call_sid = request.form.get("CallSid")
    recording_url = request.form.get("RecordingUrl")

    logging.info("Recording completed")
    logging.info(f"Call SID: {call_sid}")
    logging.info(f"Recording URL: {recording_url}")

    if not all([GITHUB_DISPATCH_URL, GITHUB_TOKEN, GITHUB_REPO]):
        logging.warning("GitHub dispatch not configured — skipping dispatch")
        return "", 200

    payload = {
        "event_type": GITHUB_EVENT_TYPE,
        "client_payload": {
            "call_sid": call_sid,
            "recording_url": recording_url
        }
    }

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    r = requests.post(GITHUB_DISPATCH_URL, json=payload, headers=headers)
    logging.info(f"GitHub dispatch response: {r.status_code}")

    return "", 200
