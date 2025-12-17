import os
import logging
import requests
from flask import Flask, request, jsonify, Response
from twilio.rest import Client

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# =========================
# Environment variables
# =========================
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM = os.environ["TWILIO_FROM"]
TWILIO_TO = os.environ["TWILIO_TO"]

GITHUB_REPO = os.environ["GITHUB_REPO"]          # e.g. "colorcodely/colorcodely-carrdco-backend"
GITHUB_TOKEN = os.environ["GH_ACTIONS_TOKEN"]

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# =========================
# Health check
# =========================
@app.route("/", methods=["GET"])
def health():
    return "OK", 200

# =========================
# Trigger daily call
# =========================
@app.route("/daily-call", methods=["POST"])
def daily_call():
    call = twilio_client.calls.create(
        to=TWILIO_TO,
        from_=TWILIO_FROM,
        url="https://colorcodely-carrdco-backend.onrender.com/twiml/record",
        trim="trim-silence",
        timeout=55,
    )

    logging.info(f"Call started: {call.sid}")
    return jsonify({"call_sid": call.sid})

# =========================
# TwiML: record audio
# =========================
@app.route("/twiml/record", methods=["POST"])
def twiml_record():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Record
        maxLength="120"
        playBeep="false"
        recordingStatusCallback="https://colorcodely-carrdco-backend.onrender.com/twilio/recording-complete"
        recordingStatusCallbackMethod="POST"
        trim="trim-silence"
    />
</Response>
"""
    return Response(xml, mimetype="text/xml")

# =========================
# Recording complete → GitHub dispatch
# =========================
@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_url = request.form.get("RecordingUrl")
    call_sid = request.form.get("CallSid")

    logging.info("Recording completed")
    logging.info(f"Call SID: {call_sid}")
    logging.info(f"Recording URL: {recording_url}")

    dispatch_payload = {
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

    resp = requests.post(
        f"https://api.github.com/repos/{GITHUB_REPO}/dispatches",
        json=dispatch_payload,
        headers=headers,
        timeout=15,
    )

    logging.info(f"GitHub dispatch status: {resp.status_code}")
    return "", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
