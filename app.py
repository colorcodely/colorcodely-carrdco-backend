import os
import logging
import requests
from flask import Flask, request, Response, jsonify
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# =========================
# Environment Variables (DEFENSIVE)
# =========================

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")

TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")
TWILIO_TO_NUMBER = os.environ.get("TWILIO_TO_NUMBER")

GITHUB_DISPATCH_URL = os.environ.get("GITHUB_DISPATCH_URL")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

# =========================
# Validate minimum requirements
# =========================

if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
    logging.error("Missing TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN")

client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
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
    if not client:
        return jsonify({"error": "Twilio client not configured"}), 500

    if not TWILIO_FROM_NUMBER or not TWILIO_TO_NUMBER:
        return jsonify({"error": "Missing FROM or TO number"}), 500

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

    if not GITHUB_DISPATCH_URL or not GITHUB_TOKEN:
        logging.warning("GitHub dispatch not configured — skipping dispatch")
        return "", 200

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
