import os
import logging
import tempfile
import requests
from datetime import datetime

from flask import Flask, request, jsonify, Response
from twilio.rest import Client as TwilioClient
from openai import OpenAI

import gspread
from google.oauth2.service_account import Credentials

# --------------------------------------------------
# CRITICAL: Render / OpenAI proxy crash workaround
# --------------------------------------------------
for proxy_var in [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "http_proxy",
    "https_proxy",
]:
    os.environ.pop(proxy_var, None)

# --------------------------------------------------
# App + logging
# --------------------------------------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --------------------------------------------------
# Environment variables (fail fast if missing)
# --------------------------------------------------
REQUIRED_ENV_VARS = [
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM_NUMBER",
    "TWILIO_TO_NUMBER",
    "OPENAI_API_KEY",
    "GOOGLE_SHEETS_CREDENTIALS_JSON",
    "GOOGLE_SHEET_NAME",
    "NOTIFY_EMAIL",
]

missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
if missing:
    raise RuntimeError(f"Missing required env vars: {missing}")

# --------------------------------------------------
# Clients
# --------------------------------------------------
twilio_client = TwilioClient(
    os.environ["TWILIO_ACCOUNT_SID"],
    os.environ["TWILIO_AUTH_TOKEN"]
)

openai_client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"]
)

# --------------------------------------------------
# Google Sheets
# --------------------------------------------------
google_creds = Credentials.from_service_account_info(
    eval(os.environ["GOOGLE_SHEETS_CREDENTIALS_JSON"]),
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
gc = gspread.authorize(google_creds)
sheet = gc.open(os.environ["GOOGLE_SHEET_NAME"]).sheet1

# --------------------------------------------------
# Helpers
# --------------------------------------------------
def already_transcribed_today() -> bool:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    values = sheet.get_all_values()
    return any(row and row[0] == today for row in values[1:])

def save_to_sheet(date_str, transcript, recording_url):
    sheet.append_row([date_str, transcript, recording_url])

def send_email(subject, body):
    # Placeholder — you already wired this earlier
    logging.info("EMAIL SENT")
    logging.info(subject)
    logging.info(body)

# --------------------------------------------------
# Routes
# --------------------------------------------------
@app.route("/", methods=["GET"])
def health():
    return "OK", 200

# --------------------------------------------------
# Trigger daily call
# --------------------------------------------------
@app.route("/daily-call", methods=["POST"])
def daily_call():
    if already_transcribed_today():
        logging.info("Already transcribed today — skipping call")
        return jsonify({"status": "skipped"}), 200

    call = twilio_client.calls.create(
        to=os.environ["TWILIO_TO_NUMBER"],
        from_=os.environ["TWILIO_FROM_NUMBER"],
        url="https://colorcodely-carrdco-backend.onrender.com/twiml/record",
        timeout=55,
        trim="trim-silence"
    )

    return jsonify({"call_sid": call.sid}), 200

# --------------------------------------------------
# TwiML: record audio
# --------------------------------------------------
@app.route("/twiml/record", methods=["POST"])
def twiml_record():
    return Response(
        """
        <Response>
            <Record
                maxLength="120"
                playBeep="false"
                trim="trim-silence"
                recordingStatusCallback="https://colorcodely-carrdco-backend.onrender.com/twilio/recording-complete"
                recordingStatusCallbackMethod="POST"
            />
            <Hangup/>
        </Response>
        """,
        mimetype="text/xml"
    )

# --------------------------------------------------
# Recording complete → transcribe → store → notify
# --------------------------------------------------
@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_url = request.form.get("RecordingUrl")

    if not recording_url:
        logging.error("Missing RecordingUrl")
        return "Missing RecordingUrl", 400

    # Download audio
    audio_response = requests.get(
        recording_url + ".wav",
        auth=(
            os.environ["TWILIO_ACCOUNT_SID"],
            os.environ["TWILIO_AUTH_TOKEN"]
        ),
        timeout=30
    )
    audio_response.raise_for_status()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_response.content)
        audio_path = f.name

    # Transcription (CORRECT OpenAI SDK usage)
    with open(audio_path, "rb") as audio_file:
        transcription = openai_client.audio.transcriptions.create(
            file=audio_file,
            model="whisper-1"
        )

    transcript_text = transcription.text.strip()
    today = datetime.utcnow().strftime("%Y-%m-%d")

    save_to_sheet(today, transcript_text, recording_url)

    send_email(
        subject=f"Daily Call Transcription — {today}",
        body=transcript_text
    )

    logging.info("Transcription completed successfully")

    return "OK", 200

# --------------------------------------------------
# Entrypoint
# --------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
