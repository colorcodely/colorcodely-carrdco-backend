import os
import requests
import logging
import datetime
import smtplib
from email.message import EmailMessage

import gspread
from google.oauth2.service_account import Credentials
import openai

logging.basicConfig(level=logging.INFO)

# ======================
# Environment variables
# ======================

TWILIO_RECORDING_URL = os.environ["TWILIO_RECORDING_URL"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

GOOGLE_CREDS_JSON = os.environ["GOOGLE_CREDS_JSON"]
GOOGLE_SHEET_NAME = os.environ["GOOGLE_SHEET_NAME"]

SMTP_SERVER = os.environ["SMTP_SERVER"]
SMTP_PORT = int(os.environ["SMTP_PORT"])
SMTP_USERNAME = os.environ["SMTP_USERNAME"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
NOTIFY_EMAIL = os.environ["NOTIFY_EMAIL"]

openai.api_key = OPENAI_API_KEY


# ======================
# Helper functions
# ======================

def download_recording(url):
    logging.info("Downloading Twilio recording...")
    audio = requests.get(url).content
    with open("recording.wav", "wb") as f:
        f.write(audio)


def transcribe_audio():
    logging.info("Transcribing audio...")
    with open("recording.wav", "rb") as audio_file:
        transcript = openai.Audio.transcribe(
            model="whisper-1",
            file=audio_file
        )
    return transcript["text"]


def append_to_sheet(date_str, time_str, transcription):
    logging.info("Appending to Google Sheet...")

    creds_info = Credentials.from_service_account_info(
        eval(GOOGLE_CREDS_JSON),
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )

    gc = gspread.authorize(creds_info)
    sheet = gc.open(GOOGLE_SHEET_NAME).sheet1

    sheet.append_row([
        date_str,
        time_str,
        transcription
    ])


def send_email(date_str, time_str, transcription):
    logging.info("Sending email notification...")

    msg = EmailMessage()
    msg["Subject"] = "New Color Code Transcription"
    msg["From"] = SMTP_USERNAME
    msg["To"] = NOTIFY_EMAIL

    msg.set_content(
        f"Date: {date_str}\n"
        f"Time: {time_str}\n\n"
        f"Transcription:\n{transcription}"
    )

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)


# ======================
# Main
# ======================

def main():
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    download_recording(TWILIO_RECORDING_URL)
    transcription = transcribe_audio()

    append_to_sheet(date_str, time_str, transcription)
    send_email(date_str, time_str, transcription)


if __name__ == "__main__":
    main()
