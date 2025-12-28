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
TWILIO_TO_NUMBER = os.environ["TWILIO_TO_NUMBER"]               # City of HSV
TWILIO_TO_NUMBER_MCOAS = os.environ["TWILIO_TO_NUMBER_MCOAS"]   # MCOAS

# GitHub
GH_ACTIONS_TOKEN = os.environ["GH_ACTIONS_TOKEN"]
GITHUB_REPO = os.environ["GITHUB_REPO"]  # e.g. colorcodely/colorcodely-carrdco-backend
GITHUB_DISPATCH_URL = f"https://api.github.com/repos/{GITHUB_REPO}/dispatches"

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# =========================
# Health Check
# =========================

@app.route("/", methods=["GET", "HEAD"])
def health():
    return "OK", 200

# =========================
# DAILY CALL — CITY OF HUNTSVILLE (existing)
# =========================

@app.route("/daily-call", methods=["POST"])
def daily_call_hsv():
    call = client.calls.create(
        to=TWILIO_TO_NUMBER,
        from_=TWILIO_FROM_NUMBER,
        url=f"{request.url_root}twiml/record/hsv",
        method="POST",
        timeout=45
    )

    logging.info(f"Huntsville call started: {call.sid}")
    return {"call_sid": call.sid}, 200

# =========================
# DAILY CALL — AL_HSV_MCOAS (NEW)
# =========================

@app.route("/daily-call/al-hsv-mcoas", methods=["POST"])
def daily_call_mcoas():
    call = client.calls.create(
        to=TWILIO_TO_NUMBER_MCOAS,
        from_=TWILIO_FROM_NUMBER,
        url=f"{request.url_root}twiml/record/al-hsv-mcoas",
        method="POST",
        timeout=45
    )

    logging.info(f"MCOAS call started: {call.sid}")
    return {"call_sid": call.sid}, 200

# =========================
# TwiML — RECORD (shared)
# =========================

@app.route("/twiml/record/<center>", methods=["POST"])
def twiml_record(center):
    response = VoiceResponse()

    response.record(
        maxLength=40,
        playBeep=False,
        trim="trim-silence",
        recordingStatusCallback=f"{request.url_root}twilio/recording-complete/{center}",
        recordingStatusCallbackMethod="POST",
        action=f"{request.url_root}twiml/end"
    )

    return Response(str(response), mimetype="text/xml")

# =========================
# TwiML END
# =========================

@app.route("/twiml/end", methods=["POST"])
def twiml_end():
    response = VoiceResponse()
    response.hangup()
    return Response(str(response), mimetype="text/xml")

# =========================
# RECORDING COMPLETE → GITHUB DISPATCH
# =========================

@app.route("/twilio/recording-complete/<center>", methods=["POST"])
def recording_complete(center):
    recording_url = request.form.get("RecordingUrl")
    call_sid = request.form.get("CallSid")

    logging.info(f"Recording completed for {center}")
    logging.info(f"Call SID: {call_sid}")
    logging.info(f"Recording URL: {recording_url}")

    headers = {
        "Authorization": f"token {GH_ACTIONS_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    if center == "al-hsv-mcoas":
        event_type = "twilio-recording-AL_HSV_MCOAS"
    else:
        event_type = "twilio-recording"

    payload = {
        "event_type": event_type,
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
