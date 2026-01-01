import os
import requests
from flask import Flask, request, Response, jsonify
from twilio.twiml.voice_response import VoiceResponse
from twilio.rest import Client

app = Flask(__name__)

# =========================
# ENV
# =========================

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM_NUMBER = os.environ["TWILIO_FROM_NUMBER"]

GITHUB_REPO = os.environ["GITHUB_REPO"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]

# Per-center outbound numbers
TWILIO_TO_NUMBER_AL_HSV = os.environ["TWILIO_TO_NUMBER"]
TWILIO_TO_NUMBER_AL_HSV_MCOAS = os.environ["TWILIO_TO_NUMBER_MCOAS"]
TWILIO_TO_NUMBER_AL_MORGANCOUNTY = os.environ["TWILIO_TO_NUMBER_AL_MORGANCOUNTY"]

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# =========================
# Helper: GitHub dispatch
# =========================

def dispatch_transcription(testing_center, recording_url):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/dispatches"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    payload = {
        "event_type": "twilio-recording",
        "client_payload": {
            "testing_center": testing_center,
            "recording_url": recording_url,
        },
    }
    requests.post(url, headers=headers, json=payload, timeout=15)

# =========================
# DAILY CALL ROUTES
# =========================

@app.post("/daily-call/al-hsv")
def call_hsv():
    call = client.calls.create(
        to=TWILIO_TO_NUMBER_AL_HSV,
        from_=TWILIO_FROM_NUMBER,
        url="https://colorcodely-carrdco-backend.onrender.com/twiml/record/AL_HSV_Municipal_Court",
        timeout=45,
        trim="trim-silence",
    )
    return jsonify({"call_sid": call.sid})

@app.post("/daily-call/al-hsv-mcoas")
def call_mcoas():
    call = client.calls.create(
        to=TWILIO_TO_NUMBER_AL_HSV_MCOAS,
        from_=TWILIO_FROM_NUMBER,
        url="https://colorcodely-carrdco-backend.onrender.com/twiml/record/AL_HSV_MCOAS",
        timeout=45,
        trim="trim-silence",
    )
    return jsonify({"call_sid": call.sid})

@app.post("/daily-call/al-morgancounty")
def call_morgancounty():
    call = client.calls.create(
        to=TWILIO_TO_NUMBER_AL_MORGANCOUNTY,
        from_=TWILIO_FROM_NUMBER,
        url="https://colorcodely-carrdco-backend.onrender.com/twiml/record/AL_MORGANCOUNTY",
        timeout=45,
        trim="trim-silence",
    )
    return jsonify({"call_sid": call.sid})

# =========================
# TWIML RECORD
# =========================

@app.post("/twiml/record/<testing_center>")
def twiml_record(testing_center):
    vr = VoiceResponse()
    vr.record(
        maxLength=45,
        playBeep=False,
        trim="trim-silence",
        action="/twiml/end",
        recordingStatusCallback=f"/twilio/recording-complete/{testing_center}",
        recordingStatusCallbackMethod="POST",
    )
    return Response(str(vr), mimetype="text/xml")

@app.post("/twiml/end")
def twiml_end():
    vr = VoiceResponse()
    vr.hangup()
    return Response(str(vr), mimetype="text/xml")

# =========================
# RECORDING CALLBACK
# =========================

@app.post("/twilio/recording-complete/<testing_center>")
def recording_complete(testing_center):
    recording_url = request.form.get("RecordingUrl")
    if recording_url:
        dispatch_transcription(testing_center, recording_url)
    return ("", 204)

if __name__ == "__main__":
    app.run()
