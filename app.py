import os
import logging
import requests
from flask import Flask, request, Response, abort
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

# Twilio
TWILIO_ACCOUNT_SID = require_env("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = require_env("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = require_env("TWILIO_FROM_NUMBER")

# GitHub dispatch
GH_ACTIONS_TOKEN = require_env("GH_ACTIONS_TOKEN")
GITHUB_REPO = require_env("GITHUB_REPO")
GITHUB_DISPATCH_URL = f"https://api.github.com/repos/{GITHUB_REPO}/dispatches"

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# === CENTER REGISTRY (CANONICAL) ===
TESTING_CENTERS = {
    "al-hsv-municipal-court": {
        "env_number": "TWILIO_TO_NUMBER",
        "testing_center": "AL_HSV_MUNICIPAL_COURT",
    },
    "al-hsv-mcoas": {
        "env_number": "TWILIO_TO_NUMBER_AL_HSV_MCOAS",
        "testing_center": "AL_HSV_MCOAS",
    },
    "al-morgancounty": {
        "env_number": "TWILIO_TO_NUMBER_AL_MORGANCOUNTY",
        "testing_center": "AL_MORGANCOUNTY",
    },
}

@app.route("/", methods=["GET"])
def health():
    return "OK", 200

@app.route("/daily-call/<center>", methods=["POST"])
def daily_call(center):
    if center not in TESTING_CENTERS:
        abort(404, "Unknown testing center")

    cfg = TESTING_CENTERS[center]
    to_number = os.environ.get(cfg["env_number"])
    if not to_number:
        abort(500, f"Missing env var: {cfg['env_number']}")

    call = client.calls.create(
        to=to_number,
        from_=TWILIO_FROM_NUMBER,
        url=f"{request.url_root}twiml/record/{center}",
        method="POST",
        timeout=45,
    )

    logging.info(f"[{center}] Call started: {call.sid}")
    return {"call_sid": call.sid}, 200

@app.route("/twiml/record/<center>", methods=["POST"])
def twiml_record(center):
    if center not in TESTING_CENTERS:
        abort(404)

    r = VoiceResponse()
    r.record(
        maxLength=40,
        playBeep=False,
        trim="trim-silence",
        recordingStatusCallback=f"{request.url_root}twilio/recording-complete/{center}",
        recordingStatusCallbackMethod="POST",
        action=f"{request.url_root}twiml/end",
    )
    return Response(str(r), mimetype="text/xml")

@app.route("/twiml/end", methods=["POST"])
def twiml_end():
    r = VoiceResponse()
    r.hangup()
    return Response(str(r), mimetype="text/xml")

@app.route("/twilio/recording-complete/<center>", methods=["POST"])
def recording_complete(center):
    if center not in TESTING_CENTERS:
        abort(404)

    recording_url = request.form.get("RecordingUrl")
    call_sid = request.form.get("CallSid")

    if not recording_url:
        abort(400, "Missing RecordingUrl")

    payload = {
        "event_type": "twilio-recording",
        "client_payload": {
            "recording_url": recording_url,
            "call_sid": call_sid,
            "testing_center": TESTING_CENTERS[center]["testing_center"],
        },
    }

    headers = {
        "Authorization": f"token {GH_ACTIONS_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    r = requests.post(GITHUB_DISPATCH_URL, json=payload, headers=headers)
    logging.info(f"[{center}] Dispatch status {r.status_code}")
    return "", 200
