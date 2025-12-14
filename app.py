import os
import json
from datetime import datetime, timezone

from flask import Flask, request, Response, jsonify
from twilio.rest import Client as TwilioClient

import gspread
from google.oauth2.service_account import Credentials

import openai


# ------------------------
# App setup
# ------------------------
app = Flask(__name__)


# ------------------------
# Environment variables
# ------------------------
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM_NUMBER = os.environ["TWILIO_FROM_NUMBER"]

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]

APP_BASE_URL = os.environ["APP_BASE_URL"].rstrip("/")


# ------------------------
# Clients
# ------------------------
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

openai.api_key = OPENAI_API_KEY

google_creds = Credentials.from_service_account_info(
    json.loads(GOOGLE_SERVICE_ACCOUNT_JSON),
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
)
gc = gspread.authorize(google_creds)

TRANSCRIPT_SHEET_NAME = "DailyTranscriptions"


# ------------------------
# Health check
# ------------------------
@app.route("/", methods=["GET", "HEAD"])
def health():
    return "OK", 200


# ------------------------
# Trigger daily call
# ------------------------
@app.route("/daily-call", methods=["POST"])
def daily_call():
    call = twilio_client.calls.create(
        to="+12564277808",
        from_=TWILIO_FROM_NUMBER,
        url=f"{APP_BASE_URL}/twiml/dial_color_line",
        method="POST",
    )
    return jsonify({"call_sid": call.sid, "status": "started"}), 200


# ------------------------
# TwiML — record ONCE
# ------------------------
@app.route("/twiml/dial_color_line", methods=["POST"])
def dial_color_line():
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Record
        maxLength="90"
        playBeep="false"
        trim="trim-silence"
        recordingStatusCallback="{APP_BASE_URL}/twilio/recording-complete"
        recordingStatusCallbackMethod="POST"
    />
    <Hangup />
</Response>
"""
    return Response(twiml, mimetype="text/xml")


# ------------------------
# Recording completed webhook
# ------------------------
@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_url = request.form.get("RecordingUrl")
    recording_sid = request.form.get("RecordingSid")

    if not recording_url or not recording_sid:
        return "Missing recording data", 400

    audio_url = f"{recording_url}.wav"

    # ---- Transcription (legacy OpenAI call — stable on Render) ----
    transcription_result = openai.Audio.transcribe(
        model="whisper-1",
        file=audio_url,
    )
    transcription = transcription_result["text"].strip()

    # ---- Color detection ----
    detected = []
    for color in [
        "red", "blue", "green", "yellow", "orange",
        "white", "black", "purple", "brown", "gray"
    ]:
        if color in transcription.lower():
            detected.append(color)

    colors_detected = ", ".join(detected) if detected else "none"

    # ---- Write to Google Sheet ----
    sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(TRANSCRIPT_SHEET_NAME)

    now = datetime.now(timezone.utc)
    sheet.append_row([
        now.strftime("%Y-%m-%d"),
        now.strftime("%H:%M:%S"),
        recording_sid,
        colors_detected,
        "auto",
        transcription,
    ])

    return "OK", 200


# ------------------------
# Local run
# ------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
