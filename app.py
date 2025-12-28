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

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM_NUMBER = os.environ["TWILIO_FROM_NUMBER"]
TWILIO_TO_NUMBER = os.environ["TWILIO_TO_NUMBER"]
TWILIO_TO_NUMBER_MCOAS = os.environ["TWILIO_TO_NUMBER_MCOAS"]

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
# DAILY CALL — HUNTSVILLE
# =========================

@app.route("/daily-call", methods=["POST"])
def daily_call_hsv():
    call = client.calls.create(
        to=TWILIO_TO_NUMBER,
        from_=TWILIO_FROM_NUMBER,
        url=f"{request.url_root}twiml/record/AL_HSV_Municipal_Court",
        timeout=45
    )
    return {"call_sid": call.sid}, 200

# =========================
# DAILY CALL — MCOAS
# =========================

@app.route("/daily-call/al-hsv-mcoas", methods=["POST"])
def daily_call_mcoas():
    call = client.calls.create(
        to=TWILIO_TO_NUMBER_MCOAS,
        from_=TWILIO_FROM_NUMBER,
        url=f"{request.url_root}twiml/record/AL_HSV_MCOAS",
        timeout=45
    )
    return {"call_sid": call.sid}, 200

# =========================
# TwiML Record
# =========================

@app.route("/twiml/record/<testing_center>", methods=["POST"])
def twiml_record(testing_center):
    response = VoiceResponse()
    response.record(
        maxLength=40,
        playBeep=False,
        trim="trim-silence",
        recordingStatusCallback=f"{request.url_root}twilio/recording-complete/{testing_center}",
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
# Recording Complete → GitHub
# =========================

@app.route("/twilio/recording-complete/<testing_center>", methods=["POST"])
def recording_complete(testing_center):
    recording_url = request.form.get("RecordingUrl")
    call_sid = request.form.get("CallSid")

    payload = {
        "event_type": "twilio-recording",
        "client_payload": {
            "recording_url": recording_url,
            "call_sid": call_sid,
            "testing_center": testing_center
        }
    }

    headers = {
        "Authorization": f"token {GH_ACTIONS_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    requests.post(GITHUB_DISPATCH_URL, json=payload, headers=headers)
    return "", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
