import os
import json
import logging
import requests
from flask import Flask, request, Response
from twilio.rest import Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# -----------------------
# Required Environment
# -----------------------
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM = os.environ.get("TWILIO_FROM")
TWILIO_TO = os.environ.get("TWILIO_TO")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")  # e.g. username/repo
GITHUB_EVENT_TYPE = "twilio-recording"

# -----------------------
# Twilio Client
# -----------------------
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# -----------------------
# Routes
# -----------------------

@app.route("/")
def health():
    return "OK", 200


@app.route("/daily-call", methods=["POST"])
def daily_call():
    call = twilio_client.calls.create(
        to=TWILIO_TO,
        from_=TWILIO_FROM,
        url="https://colorcodely-carrdco-backend.onrender.com/twiml/record",
        method="POST",
        timeout=55,
        trim="trim-silence",
    )

    logger.info(f"Call started: {call.sid}")
    return {"call_sid": call.sid}, 200


@app.route("/twiml/record", methods=["POST"])
def twiml_record():
    return Response(
        """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Record
    maxLength="120"
    playBeep="false"
    recordingStatusCallback="/twilio/recording-complete"
    recordingStatusCallbackMethod="POST"
    trim="trim-silence"
  />
</Response>""",
        mimetype="text/xml",
    )


@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_url = request.form.get("RecordingUrl")
    call_sid = request.form.get("CallSid")

    logger.info("Recording completed")
    logger.info(f"Call SID: {call_sid}")
    logger.info(f"Recording URL: {recording_url}")

    if not (GITHUB_TOKEN and GITHUB_REPO):
        logger.error("GitHub dispatch NOT configured — aborting")
        return "", 200

    dispatch_url = f"https://api.github.com/repos/{GITHUB_REPO}/dispatches"

    payload = {
        "event_type": GITHUB_EVENT_TYPE,
        "client_payload": {
            "call_sid": call_sid,
            "recording_url": recording_url,
        },
    }

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    r = requests.post(dispatch_url, headers=headers, json=payload)

    if r.status_code >= 300:
        logger.error(f"GitHub dispatch failed: {r.text}")
    else:
        logger.info("GitHub dispatch sent successfully")

    return "", 200
