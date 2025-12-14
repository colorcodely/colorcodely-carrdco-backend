import os
import logging
import tempfile
import requests
from datetime import datetime, date

from flask import Flask, request, Response, jsonify
from twilio.rest import Client as TwilioClient
from openai import OpenAI

import sheets
import emailer

# -------------------------------------------------
# Basic setup
# -------------------------------------------------
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# -------------------------------------------------
# Environment variables
# -------------------------------------------------
TWILIO_SID = os.environ.get("TWILIO_SID")
TWILIO_AUTH = os.environ.get("TWILIO_AUTH")
TWILIO_FROM = os.environ.get("TWILIO_FROM")
TWILIO_TO = os.environ.get("TWILIO_TO")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# -------------------------------------------------
# Clients
# -------------------------------------------------
twilio_client = TwilioClient(TWILIO_SID, TWILIO_AUTH)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# -------------------------------------------------
# In-memory daily guards
# (safe for single Render instance + daily cron)
# -------------------------------------------------
LAST_TRANSCRIPTION_DATE = None
PROCESSED_RECORDINGS = set()

# -------------------------------------------------
# Routes
# -------------------------------------------------
@app.route("/", methods=["GET"])
def home():
    return "OK", 200


@app.route("/daily-call", methods=["POST"])
def daily_call():
    call = twilio_client.calls.create(
        to=TWILIO_TO,
        from_=TWILIO_FROM,
        url="https://colorcodely-carrdco-backend.onrender.com/twiml/dial_color_line",
        timeout=55,
    )
    logging.info(f"Daily call started: {call.sid}")
    return jsonify({"call_sid": call.sid}), 200


@app.route("/twiml/dial_color_line", methods=["POST"])
def dial_color_line():
    return Response(
        """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Record
        maxLength="90"
        playBeep="false"
        trim="trim-silence"
        recordingStatusCallback="https://colorcodely-carrdco-backend.onrender.com/twilio/recording-complete"
        recordingStatusCallbackMethod="POST"
    />
    <Hangup/>
</Response>
""",
        mimetype="text/xml",
    )


@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    global LAST_TRANSCRIPTION_DATE

    recording_sid = request.form.get("RecordingSid")
    recording_url = request.form.get("RecordingUrl")
    call_sid = request.form.get("CallSid")

    if not recording_sid or not recording_url:
        logging.warning("Recording callback missing data")
        return ("", 204)

    # One-shot guard per recording
    if recording_sid in PROCESSED_RECORDINGS:
        logging.info(f"Recording {recording_sid} already processed")
        return ("", 204)

    PROCESSED_RECORDINGS.add(recording_sid)

    today = date.today()

    # One transcription per day guard
    if LAST_TRANSCRIPTION_DATE == today:
        logging.info("Daily transcription already completed — skipping")
        return ("", 204)

    try:
        # Download audio
        audio_resp = requests.get(
            recording_url + ".wav",
            auth=(TWILIO_SID, TWILIO_AUTH),
            timeout=30,
        )

        if audio_resp.status_code != 200:
            logging.error("Failed to download Twilio recording")
            return ("", 204)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(audio_resp.content)
            audio_path = tmp.name

        # Transcribe
        with open(audio_path, "rb") as audio_file:
            transcript = openai_client.audio.transcriptions.create(
                file=audio_file,
                model="gpt-4o-transcribe",
            )

        transcription_text = transcript.text.strip()

        # Persist
        sheets.save_daily_transcription(transcription_text)

        # Email (forced once)
        subject = f"Daily Color Code – {today.strftime('%B %d, %Y')}"
        emailer.send_email(
            to_email=os.environ.get("ALERT_EMAIL", ""),
            subject=subject,
            body=transcription_text,
        )

        LAST_TRANSCRIPTION_DATE = today

        logging.info("Daily transcription + email completed")

    except Exception:
        logging.exception("Fatal error processing recording")

    return ("", 204)


# -------------------------------------------------
# Entrypoint
# -------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
