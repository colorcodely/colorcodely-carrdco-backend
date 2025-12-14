import os
import logging
import tempfile
import requests
from datetime import datetime

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
# Google Sheets
# -------------------------------------------------
def get_sheet():
    creds_dict = eval(GOOGLE_CREDS_JSON)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(GOOGLE_SHEET_ID)
    return sheet.worksheet("DailyTranscriptions")

# -------------------------------------------------
# Email
# -------------------------------------------------
def send_email(recording_url):
    msg = EmailMessage()
    msg["Subject"] = "Daily Color Code Recording"
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_TO
    msg.set_content(f"Recording URL:\n{recording_url}")

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
    call = twilio_client.calls.create(
        to=TWILIO_TO,
        from_=TWILIO_FROM,
        url="https://colorcodely-carrdco-backend.onrender.com/twiml/dial_color_line",
        timeout=55
    )
    logging.info(f"Started call SID {call.sid}")
    return {"call_sid": call.sid, "status": "started"}, 200

@app.route("/twiml/dial_color_line", methods=["POST"])
def dial_color_line():
    return Response(
        """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Record
        maxLength="90"
        playBeep="false"
        recordingStatusCallback="https://colorcodely-carrdco-backend.onrender.com/twilio/recording-complete"
        recordingStatusCallbackMethod="POST"
        trim="trim-silence"
    />
    <Hangup/>
</Response>
""",
        mimetype="text/xml",
    )

@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    logging.info("Recording complete webhook hit")

    try:
        recording_url = request.form.get("RecordingUrl")
        recording_sid = request.form.get("RecordingSid")
        call_sid = request.form.get("CallSid")

        if not recording_url or not recording_sid:
            logging.warning("Missing recording data")
            return ("", 204)

        # -------------------------------------------------
        # Download recording from Twilio
        # -------------------------------------------------
        audio_response = requests.get(
            recording_url + ".wav",
            auth=(TWILIO_SID, TWILIO_AUTH),
            timeout=30
        )

        if audio_response.status_code != 200:
            logging.error("Failed to download recording")
            return ("", 204)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(audio_response.content)
            audio_path = tmp.name

        # -------------------------------------------------
        # Transcribe with OpenAI (CORRECT v1 API)
        # -------------------------------------------------
        with open(audio_path, "rb") as audio_file:
            transcript = openai_client.audio.transcriptions.create(
                file=audio_file,
                model="gpt-4o-transcribe"
            )

        transcription_text = transcript.text.strip()

        # -------------------------------------------------
        # Write ONE row to Google Sheet
        # -------------------------------------------------
        sheet = get_sheet()
        now = datetime.now()
        sheet.append_row([
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            call_sid,
            "n/a",
            "n/a",
            transcription_text
        ])

        # -------------------------------------------------
        # Send ONE email
        # -------------------------------------------------
        send_email(recording_url)

        logging.info("Recording processed successfully")

    except Exception:
        logging.exception("Fatal error in recording-complete")

    return ("", 204)

# -------------------------------------------------
# Entrypoint
# -------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
