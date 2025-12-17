import os
import requests
from flask import Flask, request, jsonify
from twilio.rest import Client

app = Flask(__name__)

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]

GITHUB_TOKEN = os.environ["GH_ACTIONS_TOKEN"]
GITHUB_REPO = os.environ["GITHUB_REPO"]

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_url = request.form.get("RecordingUrl")
    call_sid = request.form.get("CallSid")

    app.logger.info("Recording completed")
    app.logger.info(f"Call SID: {call_sid}")
    app.logger.info(f"Recording URL: {recording_url}")

    payload = {
        "event_type": "transcribe",  # 🚨 THIS WAS THE MISSING PIECE
        "client_payload": {
            "recording_url": recording_url,
            "call_sid": call_sid,
        }
    }

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    response = requests.post(
        f"https://api.github.com/repos/{GITHUB_REPO}/dispatches",
        json=payload,
        headers=headers,
        timeout=10,
    )

    app.logger.info(f"GitHub dispatch status: {response.status_code}")

    return "", 200


@app.route("/daily-call", methods=["POST"])
def daily_call():
    call = twilio_client.calls.create(
        to=os.environ["TWILIO_TO_NUMBER"],
        from_=os.environ["TWILIO_FROM_NUMBER"],
        url=f"{request.url_root}twiml/record",
    )

    return jsonify({"call_sid": call.sid})
