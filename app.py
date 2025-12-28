import os
import logging
import requests
from flask import Flask, request, Response
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# =========================
# Environment Variables
# =========================

# Twilio
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM_NUMBER = os.environ["TWILIO_FROM_NUMBER"]
TWILIO_TO_NUMBER = os.environ["TWILIO_TO_NUMBER"]

# GitHub
GH_ACTIONS_TOKEN = os.environ["GH_ACTIONS_TOKEN"]
GITHUB_REPO = os.environ["GITHUB_REPO"]  # e.g. "colorcodely/colorcodely-carrdco-backend"

# Derived GitHub dispatch URL (NO ENV VAR NEEDED)
GITHUB_DISPATCH_URL = f"https://api.github.com/repos/{GITHUB_REPO}/dispatches"

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

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
    call = client.calls.create(
        to=TWILIO_TO_NUMBER,
        from_=TWILIO_FROM_NUMBER,
        url=f"{request.url_root}twiml/record",
        method="POST",
        timeout=45
    )

    logging.info(f"Call started: {call.sid}")
    return {"call_sid": call.sid}, 200

# =========================
# TwiML: Record ONCE (40s max)
# =========================

@app.route("/twiml/record", methods=["POST"])
def twiml_record():
    response = VoiceResponse()

    response.record(
        maxLength=40,
        playBeep=False,
        trim="trim-silence",
        recordingStatusCallback=f"{request.url_root}twilio/recording-complete",
        recordingStatusCallbackMethod="POST",
        action=f"{request.url_root}twiml/end"
    )

    return Response(str(response), mimetype="text/xml")

# =========================
# TwiML End
# =========================

@app.route("/twiml/end", methods=["POST"])
def twiml_end():
    response = VoiceResponse()
    response.hangup()
    return Response(str(response), mimetype="text/xml")

# =========================
# Recording Complete → GitHub Dispatch
# =========================

@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_url = request.form.get("RecordingUrl")
    call_sid = request.form.get("CallSid")

    logging.info("Recording completed")
    logging.info(f"Call SID: {call_sid}")
    logging.info(f"Recording URL: {recording_url}")

    headers = {
        "Authorization": f"token {GH_ACTIONS_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    payload = {
        "event_type": "twilio-recording",
        "client_payload": {
            "recording_url": recording_url,
            "call_sid": call_sid
        }
    }

    r = requests.post(GITHUB_DISPATCH_URL, json=payload, headers=headers)
    logging.info(f"GitHub dispatch response: {r.status_code}")

    return "", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
