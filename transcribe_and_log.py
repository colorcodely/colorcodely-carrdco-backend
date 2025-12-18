import os
import logging
import requests
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime

from twilio.rest import Client
import gspread
from google.oauth2.service_account import Credentials
import openai

# -------------------------------------------------
# Logging
# -------------------------------------------------
logging.basicConfig(level=logging.INFO)

# -------------------------------------------------
# Required Environment Variables
# -------------------------------------------------
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
SMTP_FROM_NAME = os.environ["SMTP_FROM_NAME"]

NOTIFY_EMAIL = os.environ["NOTIFY_EMAIL"]

# -------------------------------------------------
# Clients
# -------------------------------------------------
openai.api_key = OPENAI_API_KEY
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# -------------------------------------------------
# Helpers
# -------------------------------------------------
def download_recording():
    logging.info("Downloading Twilio recording...")
    response = requests.get(
        TWILIO_RECORDING_URL,
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        timeout=30,
    )
    response.raise_for_status()
    return response.content


def transcribe_audio(audio_bytes):
    logging.info("Transcribing audio...")
    with open("audio.wav", "wb") as f:
        f.write(audio_bytes)

    with open("audio.wav", "rb") as audio_file:
        transcript = openai.Audio.transcribe(
            model="whisper-1",
            file=audio_file,
        )

    return transcript["text"]


def append_to_sheet(date_str, time_str, transcription):
    logging.info("Appending to Google Sheet...")

    creds = Credentials.from_service_account_info(
        eval(GOOGLE_SERVICE_ACCOUNT_JSON),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )

    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(GOOGLE_SHEET_ID).sheet1

    sheet.append_row([date_str, time_str, transcription])


def send_email(date_str, time_str, transcription):
    logging.info("Sending email notification...")

    msg = EmailMessage()
    msg["Subject"] = "ColorCodely Notification"
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USERNAME}>"
    msg["To"] = NOTIFY_EMAIL

    msg.set_content(
        f"""
Color Code Notification

DATE: {date_str}
TIME: {time_str}

TRANSCRIPTION:
{transcription}
""".strip()
    )

    context = ssl.create_default_context()

    # 🔑 IMPORTANT: Handle SSL vs STARTTLS correctly
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)


# -------------------------------------------------
# Main
# -------------------------------------------------
def main():
    audio_bytes = download_recording()
    transcription = transcribe_audio(audio_bytes)

    now = datetime.now()
    date_str = now.strftime("%A %m/%d/%Y")
    time_str = now.strftime("%H:%M:%S")

    append_to_sheet(date_str, time_str, transcription)
    send_email(date_str, time_str, transcription)


if __name__ == "__main__":
    main()
