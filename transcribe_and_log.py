import os
import json
import base64
import smtplib
import logging
import requests
from datetime import datetime
from email.message import EmailMessage

import gspread
from google.oauth2.service_account import Credentials
import openai

# =========================
# Logging
# =========================
logging.basicConfig(level=logging.INFO)

# =========================
# Environment Variables
# =========================
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_RECORDING_URL = os.environ["TWILIO_RECORDING_URL"]

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]

SMTP_SERVER = os.environ["SMTP_SERVER"]
SMTP_PORT = int(os.environ["SMTP_PORT"])
SMTP_USERNAME = os.environ["SMTP_USERNAME"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
SMTP_FROM_EMAIL = os.environ["SMTP_FROM_EMAIL"]
SMTP_FROM_NAME = os.environ["SMTP_FROM_NAME"]

# =========================
# OpenAI Setup (v0.28.x)
# =========================
openai.api_key = OPENAI_API_KEY

# =========================
# Download Recording
# =========================
def download_recording():
    logging.info("Downloading Twilio recording...")
    r = requests.get(
        TWILIO_RECORDING_URL,
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        timeout=30,
    )
    r.raise_for_status()
    return r.content

# =========================
# Transcribe Audio
# =========================
def transcribe_audio(audio_bytes):
    logging.info("Transcribing audio...")
    with open("recording.wav", "wb") as f:
        f.write(audio_bytes)

    with open("recording.wav", "rb") as audio_file:
        transcript = openai.Audio.transcribe(
            model="whisper-1",
            file=audio_file
        )

    text = transcript.get("text", "").strip()
    return clean_transcription(text)

# =========================
# Clean Repeated Phrases
# =========================
def clean_transcription(text):
    cutoff = "you must report to drug screen"
    if cutoff in text.lower():
        idx = text.lower().find(cutoff)
        return text[: idx + len(cutoff)].strip()
    return text

# =========================
# Google Sheets
# =========================
def append_to_sheet(date_str, time_str, transcription):
    logging.info("Appending to Google Sheet...")
    creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(GOOGLE_SHEET_ID)
    worksheet = sheet.worksheet("DailyTranscriptions")

    worksheet.append_row([
        date_str,
        time_str,
        "",
        "",
        "",
        transcription
    ])

# =========================
# Email Notification
# =========================
def send_email(date_str, time_str, transcription):
    logging.info("Sending email notification...")
    msg = EmailMessage()
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    msg["To"] = SMTP_USERNAME
    msg["Subject"] = "ColorCodely Daily Transcription"

    msg.set_content(
        f"A new transcription has been recorded.\n\n"
        f"Date: {date_str}\n"
        f"Time: {time_str}\n\n"
        f"Transcription:\n{transcription}"
    )

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)

# =========================
# Main
# =========================
def main():
    audio = download_recording()
    transcription = transcribe_audio(audio)

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    append_to_sheet(date_str, time_str, transcription)
    send_email(date_str, time_str, transcription)

    logging.info("Transcription workflow completed successfully.")

if __name__ == "__main__":
    main()
