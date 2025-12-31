import os
import requests
from flask import Flask, jsonify

app = Flask(__name__)

# =========================
# Twilio Credentials
# =========================

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM_NUMBER = os.environ["TWILIO_FROM_NUMBER"]

# =========================
# GitHub Dispatch
# =========================

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = "colorcodely/colorcodely-carrdco-backend"
GITHUB_EVENT_TYPE = "twilio-recording"

# =========================
# Testing Center Registry
# =========================

CENTERS = {
    "AL_HSV_Municipal_Court": {
        "to_env": "TWILIO_TO_NUMBER_AL_HSV_MUNICIPAL",
        "dispatch_workflow": "transcribe.yml",
    },
    "AL_HSV_MCOAS": {
        "to_env": "TWILIO_TO_NUMBER_AL_MCOAS",
        "dispatch_workflow": "transcribe_AL_HSV_MCOAS.yml",
    },
    "AL_MorganCounty_DailyTranscriptions": {
        "to_env": "TWILIO_TO_NUMBER_AL_MORGANCOUNTY",
        "dispatch_workflow": "transcribe_AL_MORGANCOUNTY.yml",
    },
}

# =========================
# Shared Call Logic
# =========================

def place_call(testing_center: str):
    if testing_center not in CENTERS:
        return {"error": "Unknown testing center"}, 400

    center = CENTERS[testing_center]
    to_number = os.environ.get(center["to_env"])

    if not to_number:
        return {"error": f"Missing env var: {center['to_env']}"}, 500

    twiml_url = (
        f"https://colorcodely-carrdco-backend.onrender.com"
        f"/twiml/record/{testing_center}"
    )

    response = requests.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Calls.json",
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        data={
            "To": to_number,
            "From": TWILIO_FROM_NUMBER,
            "Url": twiml_url,
            "Timeout": 45,
            "Trim": "trim-silence",
        },
        timeout=30,
    )

    response.raise_for_status()
    call_sid = response.json()["sid"]

    # Fire GitHub dispatch so the recording can be transcribed later
    dispatch_payload = {
        "event_type": GITHUB_EVENT_TYPE,
        "client_payload": {
            "testing_center": testing_center,
        },
    }

    dispatch_headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    requests.post(
        f"https://api.github.com/repos/{GITHUB_REPO}/dispatches",
        json=dispatch_payload,
        headers=dispatch_headers,
        timeout=15,
    )

    return {"call_sid": call_sid}, 200

# =========================
# Routes (Explicit = Safe)
# =========================

@app.route("/daily-call", methods=["POST"])
def daily_call_hsv():
    return jsonify(*place_call("AL_HSV_Municipal_Court"))

@app.route("/daily-call/al-hsv-mcoas", methods=["POST"])
def daily_call_mcoas():
    return jsonify(*place_call("AL_HSV_MCOAS"))

@app.route("/daily-call/al-morgancounty", methods=["POST"])
def daily_call_morgancounty():
    return jsonify(*place_call("AL_MorganCounty_DailyTranscriptions"))

# =========================
# Health Check
# =========================

@app.route("/", methods=["GET"])
def health():
    return "ColorCodely backend running", 200
