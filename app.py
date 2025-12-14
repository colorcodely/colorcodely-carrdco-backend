import os
import logging
import tempfile
import requests
from datetime import datetime, date

from flask import Flask, request, Response
from twilio.rest import Client as TwilioClient
from openai import OpenAI

import gspread
from google.oauth2.service_account import Credentials
import smtplib
from email.message import EmailMessage

# -------------------------------------------------
# Basic setup
# -------------------------------------------------
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# -------------------------------------------------
# Environment variables
# -------------------------------------------------
TWILIO_SID = os.environ["TWILIO_SID"]
TWILIO_AUTH = os.environ["TWILIO_AUTH"]
TWILIO_FROM = os.environ["TWILIO_FROM"]
TWILIO_TO = os.environ["TWILIO_TO"]

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_CREDS_JSON = os.environ["GOOGLE_CREDS_JSON"]

EMAIL_HOST = os.environ["EMAIL_HOST"]
EMAIL_PORT = int(os.environ["EMAIL_PORT"])
EMAIL_USER = os.environ["EMAIL_USER"]
EMAIL_PASS = os.environ["EMAIL_PASS"]
EMAIL_TO = os.environ["EMAIL_TO"]

# -------------------------------------------------
# Clients
# -------------------------------------------------
twilio_client = TwilioClient(TWILIO_SID, TWILIO_AUTH)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# -------------------------------------------------
# Google Sheets helpers
# -------------------------------------------------
def get_sheet():
    creds_dict = eval(GOOGLE_CREDS_JSON)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(GOOGLE_SHEET_ID)
    return sheet.worksheet("DailyTranscriptions")

def already_transcribed_today():
    sheet = get_sheet()
    rows = sheet.get_all_values()
    if not rows:
        return False

    last_row = rows[-1]
    if not last_row:
        return False

    return last_row[0] == date.today().strftime("%Y-%m-%d")

# -------------------------------------------------
# Email
# -------------------------------------------------
def send_email(transcription_text):
    msg = EmailMessage()
    msg["Subject"] = "Daily Color Code Announcement"
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_TO
    msg.set_content(transcription_text)

    with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT) as server:
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)

# -------------------------------------------------
# Routes
# -------------------------------------------------
@app.route("/")
def home():
    return "OK", 200

@app.route("/daily-call", methods=["POST"])
def daily_call():
    if already_transcribed_today():
        logging.info("Daily transcription already exists — skipping call")
        return {"status": "skipped"}, 200

    call = twilio_client.calls.create(
        to=TWILIO_TO,
        from_=TWILIO_FROM,
        url="https://colorcodely-carrdco-backend.onrender.com/twiml/start",
        timeout=60
    )

    logging.info(f"Started daily call {call.sid}")
    return {"call_sid": call.sid}, 200

# -------------------------------------------------
# TwiML — ONE-SHOT RECORDING
# -------------------------------------------------
@app.route("/twiml/start", methods=["POST"])
def twiml_start():
    return Response(
        """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial timeLimit="70">
    <Number>+12564277808</Number>
  </Dial>
</Response>
""",
        mimetype="text/xml",
    )

# -------------------------------------------------
# Recording webhook
# -------------------------------------------------
@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    if already_transcribed_today():
        logging.info("Duplicate recording callback ignored")
        return ("", 204)

    recording_url = request.form.get("RecordingUrl")
    recording_sid = request.form.get("RecordingSid")

    if not recording_url or not recording_sid:
        logging.warning("Missing recording info")
        return ("", 204)

    logging.info(f"Processing recording {recording_sid}")

    try:
        audio_response = requests.get(
            recording_url + ".wav",
            auth=(TWILIO_SID, TWILIO_AUTH),
            timeout=30
        )

        if audio_response.status_code != 200:
            raise RuntimeError("Failed to download audio")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(audio_response.content)
            audio_path = tmp.name

        with open(audio_path, "rb") as audio_file:
            transcript = openai_client.audio.transcriptions.create(
                file=audio_file,
                model="gpt-4o-transcribe"
            )

        text = transcript.text.strip()

        today = date.today().strftime("%Y-%m-%d")
        now = datetime.now().strftime("%H:%M:%S")

        sheet = get_sheet()
        sheet.append_row([today, now, recording_sid, text])

        send_email(text)

        logging.info("Daily transcription complete")

    except Exception:
        logging.exception("Transcription failure")

    return ("", 204)

# -------------------------------------------------
# Entrypoint
# -------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
