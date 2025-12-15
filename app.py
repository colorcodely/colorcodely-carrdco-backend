import os
import logging
import requests
from datetime import datetime

from flask import Flask, request, jsonify, Response
from twilio.rest import Client as TwilioClient
from openai import OpenAI

from sheets import save_daily_transcription, get_latest_transcription
from emailer import send_email

# --------------------------------------------------
# App setup
# --------------------------------------------------

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --------------------------------------------------
# Environment validation
# --------------------------------------------------

REQUIRED_ENV_VARS = [
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM_NUMBER",
    "TWILIO_TO_NUMBER",
    "OPENAI_API_KEY",
]

missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
if missing:
    raise RuntimeError(f"Missing required environment variables: {missing}")

# --------------------------------------------------
# Clients
# --------------------------------------------------

twilio_client = TwilioClient(
    os.environ["TWILIO_ACCOUNT_SID"],
    os.environ["TWILIO_AUTH_TOKEN"],
)

openai_client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"]
)

# --------------------------------------------------
# Routes
# --------------------------------------------------

@app.route("/", methods=["GET"])
def health_check():
    return "OK", 200


@app.route("/daily-call", methods=["POST"])
def daily_call():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    last_date, _ = get_latest_transcription()

    if last_date == today:
        logging.info("Transcription already exists for today. Skipping call.")
        return jsonify({"status": "already_completed_today"}), 200

    call = twilio_client.calls.create(
        to=os.environ["TWILIO_TO_NUMBER"],
        from_=os.environ["TWILIO_FROM_NUMBER"],
        url=f"{request.url_root}twiml/record",
        trim="trim-silence",
    )

    return jsonify({"call_sid": call.sid}), 200


@app.route("/twiml/record", methods=["POST"])
def twiml_record():
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
""".format(callback=f"{request.url_root}twilio/recording-complete"),
        mimetype="text/xml",
    )


@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_url = request.form.get("RecordingUrl")

    if not recording_url:
        logging.error("No RecordingUrl received")
        return "", 400

    audio_url = f"{recording_url}.wav"

    # Download audio
    r = requests.get(
        audio_url,
        auth=(
            os.environ["TWILIO_ACCOUNT_SID"],
            os.environ["TWILIO_AUTH_TOKEN"],
        ),
    )

    if r.status_code != 200:
        logging.error("Failed to download recording")
        return "", 500

    audio_path = "/tmp/recording.wav"
    with open(audio_path, "wb") as f:
        f.write(r.content)

    # Transcribe
    with open(audio_path, "rb") as audio_file:
        transcription = openai_client.audio.transcriptions.create(
            file=audio_file,
            model="gpt-4o-transcribe",
        )

    text = transcription.text.strip()

    if not text:
        logging.error("Empty transcription")
        return "", 500

    today = datetime.utcnow().strftime("%Y-%m-%d")

    save_daily_transcription(text, today)
    send_email(text)

    logging.info("Transcription saved and emailed successfully")

    return "", 204
