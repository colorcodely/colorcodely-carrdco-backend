import os
import logging
from datetime import datetime, timezone

from flask import Flask, request, Response, jsonify
from twilio.rest import Client
from openai import OpenAI

from sheets import (
    get_latest_transcription,
    save_daily_transcription,
)
from emailer import send_email


# -------------------- setup --------------------

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

REQUIRED_ENV_VARS = [
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM_NUMBER",
    "TWILIO_TO_NUMBER",
    "OPENAI_API_KEY",
]

missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
if missing:
    logging.error(f"Missing env vars: {missing}")
    raise RuntimeError("Missing required environment variables")

twilio_client = Client(
    os.environ["TWILIO_ACCOUNT_SID"],
    os.environ["TWILIO_AUTH_TOKEN"],
)

openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def today_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# -------------------- routes --------------------

@app.route("/", methods=["GET", "HEAD"])
def health():
    return "ok", 200


@app.route("/daily-call", methods=["POST"])
def daily_call():
    last_date, _ = get_latest_transcription()
    if last_date == today_utc_str():
        logging.info("Already transcribed today — skipping call")
        return jsonify({"status": "skipped"}), 200

    call = twilio_client.calls.create(
        to=os.environ["TWILIO_TO_NUMBER"],
        from_=os.environ["TWILIO_FROM_NUMBER"],
        url=f"{request.url_root.rstrip('/')}/twiml/record",
        method="POST",
        timeout=55,
    )

    return jsonify({"call_sid": call.sid}), 200


@app.route("/twiml/record", methods=["POST"])
def twiml_record():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Record
    maxLength="120"
    playBeep="false"
    trim="trim-silence"
    recordingStatusCallback="{callback}"
    recordingStatusCallbackMethod="POST"
    recordingStatusCallbackEvent="completed"
  />
  <Hangup/>
</Response>
""".format(
        callback=f"{request.url_root.rstrip('/')}/twilio/recording-complete"
    )

    return Response(xml, mimetype="text/xml")


@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_url = request.form.get("RecordingUrl")
    if not recording_url:
        logging.error("No RecordingUrl received")
        return "", 400

    audio_url = f"{recording_url}.wav"

    transcript = openai_client.audio.transcriptions.create(
        file=openai_client.files.retrieve_content(audio_url),
        model="gpt-4o-transcribe",
    ).text

    today = today_utc_str()
    save_daily_transcription(transcript, today)

    send_email(
        subject=f"Daily Call Transcription — {today}",
        body=transcript,
    )

    logging.info("Transcription saved and emailed")
    return "", 204


# -------------------- entry --------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
