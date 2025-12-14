import os
import json
import datetime
import logging
import requests

from flask import Flask, request, Response, jsonify
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

import gspread
from google.oauth2.service_account import Credentials

from openai import OpenAI
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# -------------------------
# BASIC APP SETUP
# -------------------------

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -------------------------
# ENVIRONMENT VARIABLES
# -------------------------

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM_NUMBER = os.environ["TWILIO_FROM_NUMBER"]

APP_BASE_URL = os.environ["APP_BASE_URL"]

GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

SMTP_SERVER = os.environ["SMTP_SERVER"]
SMTP_PORT = int(os.environ["SMTP_PORT"])
SMTP_USERNAME = os.environ["SMTP_USERNAME"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
SMTP_FROM_EMAIL = os.environ["SMTP_FROM_EMAIL"]
SMTP_FROM_NAME = os.environ["SMTP_FROM_NAME"]

# -------------------------
# GOOGLE SHEETS CLIENT
# -------------------------

def get_sheets_client():
    creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(GOOGLE_SHEET_ID)

# -------------------------
# TWILIO CLIENT
# -------------------------

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# -------------------------
# ROUTES
# -------------------------

@app.route("/", methods=["GET", "HEAD"])
def health():
    return "OK", 200

# -------------------------
# MANUAL / CRON TRIGGER
# -------------------------

@app.route("/daily-call", methods=["POST"])
def daily_call():
    call = twilio_client.calls.create(
        to="+12564277808",
        from_=TWILIO_FROM_NUMBER,
        url=f"{APP_BASE_URL}/twiml/dial_color_line",
        timeout=55
    )
    logging.info(f"Started call SID {call.sid}")
    return jsonify({"call_sid": call.sid, "status": "started"}), 200

# -------------------------
# TWIML: DIAL + RECORD ONCE
# -------------------------

@app.route("/twiml/dial_color_line", methods=["POST"])
def dial_color_line():
    vr = VoiceResponse()
    vr.record(
        max_length=90,
        play_beep=False,
        trim="trim-silence",
        recording_status_callback=f"{APP_BASE_URL}/twilio/recording-complete",
        recording_status_callback_method="POST"
    )
    vr.hangup()
    return Response(str(vr), mimetype="text/xml")

# -------------------------
# RECORDING COMPLETE WEBHOOK
# -------------------------

@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    try:
        logging.info("Recording complete webhook hit")

        recording_url = request.form.get("RecordingUrl")
        call_sid = request.form.get("CallSid")

        if not recording_url:
            logging.error("No RecordingUrl provided")
            return Response(status=204)

        # Download audio
        audio_response = requests.get(
            f"{recording_url}.wav",
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            timeout=30
        )
        audio_response.raise_for_status()
        audio_bytes = audio_response.content

        # Transcribe with OpenAI (SAFE INIT)
        openai_client = OpenAI(api_key=OPENAI_API_KEY)

        transcription_text = "Transcription unavailable"
        confidence = "low"

        try:
            transcript = openai_client.audio.transcriptions.create(
                file=("audio.wav", audio_bytes),
                model="gpt-4o-transcribe"
            )
            transcription_text = transcript.text
            confidence = "medium"
        except Exception as e:
            logging.error(f"Transcription failed: {e}")

        # Date / time
        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        # Write to Google Sheets
        sheet = get_sheets_client()
        daily_tab = sheet.worksheet("DailyTranscriptions")

        daily_tab.append_row([
            date_str,
            time_str,
            call_sid,
            "",  # colors_detected (optional parsing later)
            confidence,
            transcription_text
        ])

        logging.info("Row successfully written to Google Sheets")

        # Email subscribers
        subscribers_tab = sheet.worksheet("Subscribers")
        subscribers = subscribers_tab.get_all_records()

        for sub in subscribers:
            send_email(
                to_email=sub["email"],
                subject="Daily Color Code Update",
                body=transcription_text
            )

        return Response(status=204)

    except Exception as e:
        logging.exception("Fatal error in recording-complete")
        return Response(status=204)

# -------------------------
# EMAIL FUNCTION
# -------------------------

def send_email(to_email, subject, body):
    msg = MIMEMultipart()
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)
