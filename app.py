import os
import datetime
import logging
import requests
from flask import Flask, request, abort, jsonify
from twilio.rest import Client as TwilioClient

# --- local modules (unchanged, as requested) ---
from emailer import send_email
from sheets import append_transcription_row

# -------------------------------------------------
# Basic app setup
# -------------------------------------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -------------------------------------------------
# Environment variables (match your existing names)
# -------------------------------------------------
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")
TWILIO_TO_NUMBER = os.environ.get("TWILIO_TO_NUMBER")
APP_BASE_URL = os.environ.get("APP_BASE_URL")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if not all([
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_FROM_NUMBER,
    TWILIO_TO_NUMBER,
    APP_BASE_URL,
    OPENAI_API_KEY,
]):
    raise RuntimeError("Missing required environment variables")

twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# -------------------------------------------------
# Simple in-memory guard (Render restarts daily)
# -------------------------------------------------
LAST_RUN_DATE = None

# -------------------------------------------------
# Helpers
# -------------------------------------------------
def today_cst():
    return datetime.datetime.utcnow() - datetime.timedelta(hours=6)

def already_ran_today():
    global LAST_RUN_DATE
    today = today_cst().date()
    return LAST_RUN_DATE == today

def mark_ran_today():
    global LAST_RUN_DATE
    LAST_RUN_DATE = today_cst().date()

def whisper_transcribe(recording_url):
    audio = requests.get(
        recording_url,
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        timeout=30,
    )

    r = requests.post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
        files={
            "file": ("audio.wav", audio.content, "audio/wav"),
            "model": (None, "whisper-1"),
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json().get("text", "")

# -------------------------------------------------
# Routes
# -------------------------------------------------
@app.route("/", methods=["GET"])
def health():
    return "ok", 200

@app.route("/daily-call", methods=["POST"])
def daily_call():
    if already_ran_today():
        return jsonify({"status": "skipped"}), 200

    call = twilio_client.calls.create(
        to=TWILIO_TO_NUMBER,
        from_=TWILIO_FROM_NUMBER,
        url=f"{APP_BASE_URL}/twiml/dial_color_line",
        timeout=55,
    )

    mark_ran_today()
    return jsonify({"call_sid": call.sid}), 200

@app.route("/twiml/dial_color_line", methods=["POST"])
def dial_color_line():
    return (
        """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Record
    maxLength="90"
    playBeep="false"
    trim="trim-silence"
    recordingStatusCallback="{}/twilio/recording-complete"
    recordingStatusCallbackMethod="POST"/>
  <Hangup/>
</Response>""".format(APP_BASE_URL),
        200,
        {"Content-Type": "text/xml"},
    )

@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_url = request.form.get("RecordingUrl")
    call_sid = request.form.get("CallSid")

    if not recording_url or not call_sid:
        abort(400)

    try:
        text = whisper_transcribe(recording_url)
    except Exception as e:
        logging.exception("Whisper failed")
        text = "Transcription error"

    append_transcription_row(
        date=today_cst().date().isoformat(),
        time=today_cst().time().strftime("%H:%M:%S"),
        call_sid=call_sid,
        transcription=text,
    )

    send_email(
        subject="Daily Color Code Transcription",
        body=text or "No transcription text was provided.",
    )

    return ("", 204)

# -------------------------------------------------
# Entrypoint
# -------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
