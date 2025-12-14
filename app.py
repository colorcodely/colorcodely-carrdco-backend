import os
import logging
from datetime import datetime, date

from flask import Flask, request, Response, jsonify
from twilio.rest import Client
import requests

from sheets import save_daily_transcription, get_latest_transcription
from emailer import send_email

# --------------------------------------------------
# Basic setup
# --------------------------------------------------

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --------------------------------------------------
# Environment variables (NO guessing)
# --------------------------------------------------

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")
TWILIO_TO_NUMBER = os.environ.get("TWILIO_TO_NUMBER")
APP_BASE_URL = os.environ.get("APP_BASE_URL")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

REQUIRED_VARS = [
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_FROM_NUMBER,
    TWILIO_TO_NUMBER,
    APP_BASE_URL,
    OPENAI_API_KEY,
]

if not all(REQUIRED_VARS):
    raise RuntimeError("Missing required environment variables")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# --------------------------------------------------
# Helpers
# --------------------------------------------------

def today_str():
    return date.today().strftime("%Y-%m-%d")


def already_transcribed_today():
    last_date, _ = get_latest_transcription()
    return last_date == today_str()


def transcribe_with_whisper(recording_url: str) -> str:
    """
    Fetch Twilio recording and send to OpenAI Whisper.
    """
    audio = requests.get(
        recording_url,
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        timeout=30,
    )

    if audio.status_code != 200:
        raise RuntimeError("Failed to download recording")

    import openai
    openai.api_key = OPENAI_API_KEY

    response = openai.audio.transcriptions.create(
        file=("audio.wav", audio.content),
        model="gpt-4o-transcribe",
    )

    return response.text.strip()


# --------------------------------------------------
# Routes
# --------------------------------------------------

@app.route("/", methods=["GET"])
def health_check():
    return "OK", 200


@app.route("/daily-call", methods=["POST"])
def daily_call():
    if already_transcribed_today():
        logging.info("Transcription already exists for today — skipping call.")
        return jsonify({"status": "skipped"}), 200

    call = twilio_client.calls.create(
        to=TWILIO_TO_NUMBER,
        from_=TWILIO_FROM_NUMBER,
        url=f"{APP_BASE_URL}/twiml/record",
        timeout=55,
    )

    logging.info(f"Call initiated: {call.sid}")
    return jsonify({"status": "calling", "call_sid": call.sid}), 200


@app.route("/twiml/record", methods=["POST"])
def twiml_record():
    """
    Single-shot recording. No looping.
    """
    return Response(
        """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Record
        maxLength="120"
        playBeep="false"
        trim="trim-silence"
        recordingStatusCallback="{callback}"
        recordingStatusCallbackMethod="POST"
    />
    <Hangup/>
</Response>
""".format(
            callback=f"{APP_BASE_URL}/twilio/recording-complete"
        ),
        mimetype="text/xml",
    )


@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    if already_transcribed_today():
        logging.info("Recording callback ignored — already transcribed today.")
        return ("", 204)

    recording_url = request.form.get("RecordingUrl")
    call_sid = request.form.get("CallSid")

    if not recording_url:
        logging.error("No RecordingUrl received")
        return ("", 400)

    try:
        transcription = transcribe_with_whisper(recording_url)
    except Exception as e:
        logging.exception("Transcription failed")
        send_email(
            subject="ColorCodeLy — Transcription Failed",
            body=str(e),
        )
        return ("", 500)

    save_daily_transcription(transcription)

    send_email(
        subject=f"Color Codes for {today_str()}",
        body=transcription,
    )

    logging.info(f"Transcription saved for call {call_sid}")
    return ("", 204)


# --------------------------------------------------
# Entrypoint (Render/Gunicorn)
# --------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
