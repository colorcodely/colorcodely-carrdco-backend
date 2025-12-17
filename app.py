import os
import logging
import requests
from flask import Flask, request, Response, jsonify
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Record

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# =========================
# Environment Variables
# =========================

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]

# IMPORTANT: use the variable that actually exists in Render
TWILIO_FROM_NUMBER = os.environ["TWILIO_FROM_NUMBER"]
TWILIO_TO_NUMBER = os.environ["TWILIO_TO_NUMBER"]

GITHUB_DISPATCH_URL = os.environ["GITHUB_DISPATCH_URL"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# =========================
# Health Check
# =========================

@app.route("/", methods=["GET", "HEAD"])
def health():
    return "OK", 200

# =========================
# Trigger Call
# =========================

@app.route("/daily-call", methods=["POST"])
def daily_call():
    call = client.calls.create(
        to=TWILIO_TO_NUMBER,
        from_=TWILIO_FROM_NUMBER,
        url=f"{request.url_root}twiml/record",
        timeout=55,
        trim="trim-silence",
    )

    logging.info(f"Call started: {call.sid}")
    return jsonify({"call_sid": call.sid})

# =========================
# TwiML Record Endpoint
# =========================

@app.route("/twiml/record", methods=["POST"])
def twiml_record():
    response = VoiceResponse()

    response.record(
        maxLength=120,
        playBeep=False,
        trim="trim-silence",
        recordingStatusCallback=f"{request.url_root}twilio/recording-complete",
        recordingStatusCallbackMethod="POST",
    )

    return Response(str(response), mimetype="text/xml")

# =========================
# Recording Complete Callback
# =========================

@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_url = request.form.get("RecordingUrl")
    call_sid = request.form.get("CallSid")

    logging.info("Recording completed")
    logging.info(f"Call SID: {call_sid}")
    logging.info(f"Recording URL: {recording_url}")

    payload = {
        "event_type": "transcribe",
        "client_payload": {
            "recording_url": recording_url,
            "call_sid": call_sid,
        },
    }

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    r = requests.post(GITHUB_DISPATCH_URL, json=payload, headers=headers)
    logging.info(f"GitHub dispatch status: {r.status_code}")

    return "", 200

# =========================
# App Entry
# =========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
