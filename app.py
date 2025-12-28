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

TWILIO_TO_NUMBER_HSV = os.environ["TWILIO_TO_NUMBER"]          # Huntsville
TWILIO_TO_NUMBER_MCOAS = os.environ["TWILIO_TO_NUMBER_MCOAS"]  # MCOAS

# GitHub
GH_ACTIONS_TOKEN = os.environ["GH_ACTIONS_TOKEN"]
GITHUB_REPO = os.environ["GITHUB_REPO"]  # e.g. "colorcodely/colorcodely-carrdco-backend"
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

    headers = {
        "Authorization": f"token {GH_ACTIONS_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    # -------------------------
    # 1️⃣ Huntsville Municipal Court (daily)
    # -------------------------

    call_hsv = client.calls.create(
        to=TWILIO_TO_NUMBER_HSV,
        from_=TWILIO_FROM_NUMBER,
        url=f"{request.url_root}twiml/record",
        method="POST",
        timeout=45
    )

    logging.info(f"Huntsville call started: {call_hsv.sid}")

    payload_hsv = {
        "event_type": "twilio-recording",
        "client_payload": {
            "call_sid": call_hsv.sid
        }
    }

    requests.post(GITHUB_DISPATCH_URL, json=payload_hsv, headers=headers)

    # -------------------------
    # 2️⃣ Madison County Office of Alternative Sentencing
    #     (Weekdays only)
    # -------------------------

    if weekday < 5:  # Mon–Fri only
        call_mcoas = client.calls.create(
            to=TWILIO_TO_NUMBER_MCOAS,
            from_=TWILIO_FROM_NUMBER,
            url=f"{request.url_root}twiml/record",
            method="POST",
            timeout=45
        )

        logging.info(f"MCOAS call started: {call_mcoas.sid}")

        payload_mcoas = {
            "event_type": "twilio-recording-AL_HSV_MCOAS",
            "client_payload": {
                "call_sid": call_mcoas.sid
            }
        }

        requests.post(GITHUB_DISPATCH_URL, json=payload_mcoas, headers=headers)
    else:
        logging.info("Weekend detected — skipping MCOAS call")

    return {"status": "calls initiated"}, 200

# =========================
# TwiML: Record ONCE
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
    logging.info(f"Recording dispatch status: {r.status_code}")

    return "", 200

# =========================
# Run
# =========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
