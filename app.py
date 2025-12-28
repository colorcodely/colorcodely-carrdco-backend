import os
import logging
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
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
TWILIO_TO_NUMBER = os.environ["TWILIO_TO_NUMBER"]  # Huntsville Municipal
MCOAS_TO_NUMBER = "2565338943"  # Madison County Office of Alternative Sentencing

# GitHub
GH_ACTIONS_TOKEN = os.environ["GH_ACTIONS_TOKEN"]
GITHUB_REPO = os.environ["GITHUB_REPO"]

GITHUB_DISPATCH_URL = f"https://api.github.com/repos/{GITHUB_REPO}/dispatches"

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# =========================
# Health Check
# =========================

@app.route("/", methods=["GET", "HEAD"])
def health():
    return "OK", 200

# =========================
# Trigger Daily Calls
# =========================

@app.route("/daily-call", methods=["POST"])
def daily_call():
    now = datetime.now(tz=ZoneInfo("America/Chicago"))
    weekday = now.weekday()  # Monday=0, Sunday=6

    # --- Huntsville Municipal Court (daily) ---
    call_hsv = client.calls.create(
        to=TWILIO_TO_NUMBER,
        from_=TWILIO_FROM_NUMBER,
        url=f"{request.url_root}twiml/record",
        method="POST",
        timeout=45
    )
    logging.info(f"Huntsville call started: {call_hsv.sid}")

    # --- MCOAS (weekdays only) ---
    if weekday < 5:
        call_mcoas = client.calls.create(
            to=MCOAS_TO_NUMBER,
            from_=TWILIO_FROM_NUMBER,
            url=f"{request.url_root}twiml/record-mcoas",
            method="POST",
            timeout=45
        )
        logging.info(f"MCOAS call started: {call_mcoas.sid}")

    return {"status": "calls triggered"}, 200

# =========================
# TwiML — Huntsville
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
# TwiML — MCOAS
# =========================

@app.route("/twiml/record-mcoas", methods=["POST"])
def twiml_record_mcoas():
    response = VoiceResponse()
    response.record(
        maxLength=40,
        playBeep=False,
        trim="trim-silence",
        recordingStatusCallback=f"{request.url_root}twilio/recording-complete-mcoas",
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
# Recording Complete — Huntsville
# =========================

@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_url = request.form.get("RecordingUrl")
    call_sid = request.form.get("CallSid")

    payload = {
        "event_type": "twilio-recording",
        "client_payload": {
            "recording_url": recording_url,
            "call_sid": call_sid
        }
    }

    headers = {
        "Authorization": f"token {GH_ACTIONS_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    requests.post(GITHUB_DISPATCH_URL, json=payload, headers=headers)
    logging.info("Dispatched Huntsville recording")

    return "", 200

# =========================
# Recording Complete — MCOAS
# =========================

@app.route("/twilio/recording-complete-mcoas", methods=["POST"])
def recording_complete_mcoas():
    recording_url = request.form.get("RecordingUrl")
    call_sid = request.form.get("CallSid")

    payload = {
        "event_type": "twilio-recording-AL_HSV_MCOAS",
        "client_payload": {
            "recording_url": recording_url,
            "call_sid": call_sid
        }
    }

    headers = {
        "Authorization": f"token {GH_ACTIONS_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    requests.post(GITHUB_DISPATCH_URL, json=payload, headers=headers)
    logging.info("Dispatched MCOAS recording")

    return "", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
