import os
import requests
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# =========================
# Environment Variables
# =========================

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]

# IMPORTANT:
# GitHub token is ONLY required when dispatching workflows
# Render does NOT provide this automatically
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

GITHUB_REPO = "colorcodely/colorcodely-carrdco-backend"

# =========================
# TwiML: Record Call
# =========================

@app.route("/twiml/record/<testing_center>", methods=["POST"])
def record_call(testing_center):
    recording_callback = (
        f"https://colorcodely-carrdco-backend.onrender.com"
        f"/twilio/recording-complete/{testing_center}"
    )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Record
    action="/twiml/end"
    maxLength="40"
    playBeep="false"
    trim="trim-silence"
    recordingStatusCallback="{recording_callback}"
    recordingStatusCallbackMethod="POST"
  />
</Response>
"""
    return Response(xml, mimetype="text/xml")


@app.route("/twiml/end", methods=["POST"])
def end_call():
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>',
        mimetype="text/xml",
    )

# =========================
# Twilio → GitHub Dispatch
# =========================

@app.route("/twilio/recording-complete/<testing_center>", methods=["POST"])
def recording_complete(testing_center):
    if not GITHUB_TOKEN:
        return jsonify({
            "error": "GITHUB_TOKEN not configured on this service"
        }), 500

    recording_url = request.form.get("RecordingUrl")
    if not recording_url:
        return jsonify({"error": "Missing RecordingUrl"}), 400

    workflow_map = {
        "AL_HSV_Municipal_Court": "transcribe.yml",
        "AL_HSV_MCOAS": "transcribe_AL_HSV_MCOAS.yml",
        "AL_MorganCounty_DailyTranscriptions": "transcribe_AL_MORGANCOUNTY.yml",
    }

    workflow = workflow_map.get(testing_center)
    if not workflow:
        return jsonify({"error": "Unknown testing center"}), 400

    url = f"https://api.github.com/repos/{GITHUB_REPO}/dispatches"

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    payload = {
        "event_type": "twilio-recording",
        "client_payload": {
            "recording_url": recording_url,
        },
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=15)

    if resp.status_code != 204:
        return jsonify({
            "error": "GitHub dispatch failed",
            "status": resp.status_code,
            "body": resp.text,
        }), 500

    return jsonify({"status": "workflow dispatched"}), 200

# =========================
# Daily Call Triggers
# =========================

@app.route("/daily-call", methods=["POST"])
def daily_call_hsv():
    return _make_daily_call(
        os.environ["TWILIO_TO_NUMBER"],
        "AL_HSV_Municipal_Court"
    )

@app.route("/daily-call/al-hsv-mcoas", methods=["POST"])
def daily_call_mcoas():
    return _make_daily_call(
        os.environ["TWILIO_TO_NUMBER_MCOAS"],
        "AL_HSV_MCOAS"
    )

@app.route("/daily-call/al-morgancounty", methods=["POST"])
def daily_call_morgan():
    return _make_daily_call(
        os.environ["TWILIO_TO_NUMBER_AL_MORGANCOUNTY"],
        "AL_MorganCounty_DailyTranscriptions"
    )

# =========================
# Call Helper
# =========================

def _make_daily_call(to_number, testing_center):
    from twilio.rest import Client

    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    call = client.calls.create(
        to=to_number,
        from_=os.environ["TWILIO_FROM_NUMBER"],
        url=f"https://colorcodely-carrdco-backend.onrender.com/twiml/record/{testing_center}",
        timeout=45,
        trim="trim-silence",
    )

    return jsonify({"call_sid": call.sid})
