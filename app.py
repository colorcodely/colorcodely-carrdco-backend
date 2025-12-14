import os
import json
import datetime
import logging
import requests
import smtplib

from flask import Flask, request, Response, jsonify
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

import gspread
from google.oauth2.service_account import Credentials
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# -------------------------
# APP SETUP
# -------------------------

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -------------------------
# ENV VARS
# -------------------------

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM_NUMBER = os.environ["TWILIO_FROM_NUMBER"]
APP_BASE_URL = os.environ["APP_BASE_URL"]

GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]

SMTP_SERVER = os.environ["SMTP_SERVER"]
SMTP_PORT = int(os.environ["SMTP_PORT"])
SMTP_USERNAME = os.environ["SMTP_USERNAME"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
SMTP_FROM_EMAIL = os.environ["SMTP_FROM_EMAIL"]
SMTP_FROM_NAME = os.environ["SMTP_FROM_NAME"]

# -------------------------
# CLIENTS
# -------------------------

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

def get_sheets():
    creds = Credentials.from_service_account_info(
        json.loads(GOOGLE_SERVICE_ACCOUNT_JSON),
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(GOOGLE_SHEET_ID)

# -------------------------
# ROUTES
# -------------------------

@app.route("/", methods=["GET", "HEAD"])
def health():
    return "OK", 200

@app.route("/daily-call", methods=["POST"])
def daily_call():
    call = twilio_client.calls.create(
        to="+12564277808",
        from_=TWILIO_FROM_NUMBER,
        url=f"{APP_BASE_URL}/twiml/dial_color_line",
        timeout=55
    )
    logging.info(f"Call started: {call.sid}")
    return jsonify({"call_sid": call.sid, "status": "started"}), 200

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

@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    try:
        logging.info("Recording webhook received")

        call_sid = request.form.get("CallSid")
        recording_sid = request.form.get("RecordingSid")
        recording_url = request.form.get("RecordingUrl")

        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        sheet = get_sheets()
        daily = sheet.worksheet("DailyTranscriptions")

        daily.append_row([
            date_str,
            time_str,
            call_sid,
            recording_sid,
            "n/a",
            recording_url
        ])

        logging.info("Row written to Google Sheets")

        subscribers = sheet.worksheet("Subscribers").get_all_records()
        for sub in subscribers:
            send_email(
                sub["email"],
                "Daily Color Code Recording",
                f"Recording URL:\n{recording_url}"
            )

        return Response(status=204)

    except Exception:
        logging.exception("Recording handler failed")
        return Response(status=204)

# -------------------------
# EMAIL
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
