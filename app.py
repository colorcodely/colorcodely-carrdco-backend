import os
import logging
import requests
from flask import Flask, request, jsonify, Response
from twilio.rest import Client

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# =========================
# Environment Variables
# =========================

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM_NUMBER = os.environ["TWILIO_FROM"]
TWILIO_TO_NUMBER = os.environ["TWILIO_TO_NUMBER"]

APP_BASE_URL = os.environ.get(
    "APP_BASE_URL",
    "https://colorcodely-carrdco-backend.onrender.com"
)

GH_ACTIONS_TOKEN = os.environ.get("GH_ACTIONS_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# =========================
# Health Check
# =========================

@app.route("/", methods=["GET", "HEAD"])
def health():
    return "OK", 200

# =========================
# Trigger Daily Call
# =========================

@app.route("/daily-call", methods=["POST"])
def daily_call():
    call = twilio_client.calls.create(
        to=TWILIO_TO_NUMBER,
        from_=TWILIO_FROM_NUMBER,
        url=f"{APP_BASE_URL}/twiml/record",
        timeout=55,
        trim="trim-silence",
    )

    logging.info(f"Call started: {call.sid}")
    return jsonify({"call_sid": call.sid})

# =========================
# TwiML — RECORD ONCE, THEN HANG UP
# =========================

@app.route("/twiml/record", methods=["POST"])
def twiml_record():
    """
    This endpoint MUST return a single <Record> with no loop.
    When the recording finishes, Twilio will POST to
    /twilio/recording-complete and then end the call.
    """

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Record
    maxLength="120"
    playBeep="false"
    trim="trim-silence"
    recordingStatusCallback="{APP_BASE_URL}/twilio/recording-complete"
    recordingStatusCallbackMethod="POST"
  />
</Response>
"""
    return Response(twiml, mimetype="text/xml")

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

    # Fire GitHub repository_dispatch
    if GH_ACTIONS_TOKEN and GITHUB_REPO and recording_url:
        dispatch_url = f"https://api.github.com/repos/{GITHUB_REPO}/dispatches"
        headers = {
            "Authorization": f"token {GH_ACTIONS_TOKEN}",
            "Accept": "application/vnd.github+json",
        }
        payload = {
            "event_type": "twilio-recording",
            "client_payload": {
                "recording_url": recording_url,
                "call_sid": call_sid,
            },
        }

        response = requests.post(
            dispatch_url, headers=headers, json=payload, timeout=10
        )

        logging.info(f"GitHub dispatch response: {response.status_code}")
    else:
        logging.warning("GitHub dispatch not configured — skipping dispatch")

    return "", 200

# =========================
# Entrypoint
# =========================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
