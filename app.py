import os
import requests
from flask import Flask, request, Response, jsonify
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

app = Flask(__name__)

# --- Environment variables ---
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM = os.environ["TWILIO_FROM"]
TWILIO_TO = os.environ["TWILIO_TO"]

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = os.environ["GITHUB_REPO"]  # e.g. colorcodely/colorcodely-carrdco-backend

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# --- Health check ---
@app.route("/", methods=["GET"])
def health():
    return "OK", 200

# --- Trigger outbound call ---
@app.route("/daily-call", methods=["POST"])
def daily_call():
    call = client.calls.create(
        to=TWILIO_TO,
        from_=TWILIO_FROM,
        url="https://colorcodely-carrdco-backend.onrender.com/twiml/record",
        method="POST",
    )

    print(f"Call started: {call.sid}")
    return jsonify({"call_sid": call.sid})

# --- TwiML: RECORD ONCE, THEN HANG UP ---
@app.route("/twiml/record", methods=["POST"])
def twiml_record():
    response = VoiceResponse()

    response.record(
        max_length=120,
        play_beep=False,
        trim="trim-silence",
        recording_status_callback="https://colorcodely-carrdco-backend.onrender.com/twilio/recording-complete",
        recording_status_callback_method="POST",
    )

    response.hangup()

    return Response(str(response), mimetype="text/xml")

# --- Recording complete webhook ---
@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_url = request.form.get("RecordingUrl")
    call_sid = request.form.get("CallSid")

    print("Recording completed")
    print(f"Call SID: {call_sid}")
    print(f"Recording URL: {recording_url}")

    # Dispatch GitHub workflow
    dispatch_url = f"https://api.github.com/repos/{GITHUB_REPO}/dispatches"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    payload = {
        "event_type": "twilio-recording",
        "client_payload": {
            "recording_url": recording_url
        },
    }

    r = requests.post(dispatch_url, json=payload, headers=headers)
    print("GitHub dispatch response:", r.status_code)

    return "", 200
