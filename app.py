import os
import logging
import tempfile
import requests
from datetime import date

from flask import Flask, request, Response, jsonify
from twilio.rest import Client as TwilioClient

import openai
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

openai.api_key = os.environ.get("OPENAI_API_KEY")

# -------------------------------------------------
# Clients
# -------------------------------------------------
twilio_client = TwilioClient(TWILIO_SID, TWILIO_AUTH)

# -------------------------------------------------
# Guards
# -------------------------------------------------
PROCESSED_RECORDINGS = set()
LAST_TRANSCRIPTION_DATE = None

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
    logging.info(f"Call started: {call.sid}")
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

    if not recording_sid or not recording_url:
        return ("", 204)

    if recording_sid in PROCESSED_RECORDINGS:
        return ("", 204)

    today = date.today()

    if LAST_TRANSCRIPTION_DATE == today:
        return ("", 204)

    PROCESSED_RECORDINGS.add(recording_sid)

    try:
        audio_resp = requests.get(
            recording_url + ".wav",
            auth=(TWILIO_SID, TWILIO_AUTH),
            timeout=30,
        )

        if audio_resp.status_code != 200:
            return ("", 204)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(audio_resp.content)
            audio_path = tmp.name

        with open(audio_path, "rb") as audio_file:
            transcript = openai.Audio.transcribe(
                model="whisper-1",
                file=audio_file,
                prompt=(
                    "This is a daily color code announcement. "
                    "Colors are spoken clearly and separated by commas."
                ),
            )

        transcription_text = transcript["text"].strip()

        sheets.save_daily_transcription(transcription_text)

        emailer.send_email(
            to_email=os.environ.get("ALERT_EMAIL", ""),
            subject=f"Daily Color Code – {today.strftime('%B %d, %Y')}",
            body=transcription_text,
        )

        LAST_TRANSCRIPTION_DATE = today

        logging.info("Daily transcription complete")

    except Exception:
        logging.exception("Recording processing failed")

    return ("", 204)


# -------------------------------------------------
# Entrypoint
# -------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
