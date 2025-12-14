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
# Environment variables (SAFE)
# -------------------------------------------------
TWILIO_SID = os.getenv("TWILIO_SID") or os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH") or os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM = os.getenv("TWILIO_FROM") or os.getenv("TWILIO_FROM_NUMBER")
TWILIO_TO = os.getenv("TWILIO_TO")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "465"))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_TO = os.getenv("EMAIL_TO")

# -------------------------------------------------
# Validate critical config
# -------------------------------------------------
if not all([TWILIO_SID, TWILIO_AUTH, TWILIO_FROM, TWILIO_TO]):
    logging.warning("⚠️ Twilio environment variables incomplete")

if not OPENAI_API_KEY:
    logging.warning("⚠️ OpenAI API key missing")

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
    return rows[-1][0] == date.today().strftime("%Y-%m-%d")

# -------------------------------------------------
# Email
# -------------------------------------------------
def send_email(text):
    if not all([EMAIL_HOST, EMAIL_USER, EMAIL_PASS, EMAIL_TO]):
        logging.warning("Email not configured — skipping send")
        return

    msg = EmailMessage()
    msg["Subject"] = "Daily Color Code Announcement"
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_TO
    msg.set_content(text)

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
        logging.info("Already transcribed today — skipping call")
        return {"status": "skipped"}, 200

    call = twilio_client.calls.create(
        to=TWILIO_TO,
        from_=TWILIO_FROM,
        url="https://colorcodely-carrdco-backend.onrender.com/twiml/start",
        timeout=70
    )

    logging.info(f"Started call {call.sid}")
    return {"call_sid": call.sid}, 200

# -------------------------------------------------
# TwiML (ONE-SHOT, NO LOOP)
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
        logging.info("Duplicate recording ignored")
        return ("", 204)

    recording_url = request.form.get("RecordingUrl")
    if not recording_url:
        return ("", 204)

    try:
        audio = requests.get(
            recording_url + ".wav",
            auth=(TWILIO_SID, TWILIO_AUTH),
            timeout=30
        )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            f.write(audio.content)
            path = f.name

        with open(path, "rb") as audio_file:
            transcript = openai_client.audio.transcriptions.create(
                file=audio_file,
                model="gpt-4o-transcribe"
            )

        text = transcript.text.strip()

        sheet = get_sheet()
        sheet.append_row([
            date.today().strftime("%Y-%m-%d"),
            datetime.now().strftime("%H:%M:%S"),
            text
        ])

        send_email(text)
        logging.info("Transcription complete")

    except Exception:
        logging.exception("Transcription failed")

    return ("", 204)

# -------------------------------------------------
# Entrypoint
# -------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
