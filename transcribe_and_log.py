import os
import requests
import tempfile
from datetime import datetime
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import openai
from google.oauth2 import service_account
from googleapiclient.discovery import build

# =========================
# Environment Variables
# =========================

openai.api_key = os.environ["OPENAI_API_KEY"]

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_RECORDING_URL = os.environ["TWILIO_RECORDING_URL"]
CALL_SID = os.environ.get("CALL_SID", "")

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]

SMTP_SERVER = os.environ["SMTP_SERVER"]
SMTP_PORT = int(os.environ["SMTP_PORT"])
SMTP_USERNAME = os.environ["SMTP_USERNAME"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
SMTP_FROM_EMAIL = os.environ["SMTP_FROM_EMAIL"]
SMTP_FROM_NAME = os.environ["SMTP_FROM_NAME"]
NOTIFY_EMAIL = os.environ["NOTIFY_EMAIL"]

# =========================
# Download Recording
# =========================

response = requests.get(
    f"{TWILIO_RECORDING_URL}.wav",
    auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
    timeout=30,
)
response.raise_for_status()

with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
    f.write(response.content)
    audio_path = f.name

# =========================
# Transcribe (Whisper)
# =========================

with open(audio_path, "rb") as audio_file:
    transcription = openai.Audio.transcribe(
        model="whisper-1",
        file=audio_file,
    )

raw_text = transcription["text"].strip().lower()

# =========================
# HARD STOP CLEANUP
# =========================

STOP_PHRASE = "you must report to drug screen"

match = re.search(
    rf"(.*?{STOP_PHRASE}\.)",
    raw_text,
    re.IGNORECASE | re.DOTALL,
)

if match:
    cleaned_text = match.group(1).strip()
else:
    cleaned_text = raw_text  # fallback, should rarely happen

# =========================
# Google Sheets Append
# =========================

creds = service_account.Credentials.from_service_account_info(
    eval(GOOGLE_SERVICE_ACCOUNT_JSON),
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
)

service = build("sheets", "v4", credentials=creds)

now = datetime.now()

row = [
    now.strftime("%Y-%m-%d"),   # date
    now.strftime("%H:%M:%S"),   # time
    CALL_SID,                   # source_call_sid
    "",                          # colors_detected (future)
    "",                          # confidence (future)
    cleaned_text                 # transcription
]

service.spreadsheets().values().append(
    spreadsheetId=GOOGLE_SHEET_ID,
    range="DailyTranscriptions!A:F",
    valueInputOption="RAW",
    body={"values": [row]},
).execute()

# =========================
# Email Notification
# =========================

subject = "New Color Code Transcription"

body = (
    "A new transcription has been recorded.\n\n"
    f"Date: {row[0]}\n"
    f"Time: {row[1]}\n\n"
    "Transcription:\n"
    f"{cleaned_text}"
)

message = MIMEMultipart()
message["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
message["To"] = NOTIFY_EMAIL
message["Subject"] = subject
message.attach(MIMEText(body, "plain"))

with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
    server.starttls()
    server.login(SMTP_USERNAME, SMTP_PASSWORD)
    server.send_message(message)
