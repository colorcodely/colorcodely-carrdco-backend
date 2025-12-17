import os
import requests
import tempfile
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import openai
from google.oauth2 import service_account
from googleapiclient.discovery import build

# =========================
# Environment Variables
# =========================

# OpenAI
openai.api_key = os.environ["OPENAI_API_KEY"]

# Twilio
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_RECORDING_URL = os.environ["TWILIO_RECORDING_URL"]

# Google Sheets
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]

# Email / SMTP (MATCHES GITHUB SECRETS EXACTLY)
SMTP_SERVER = os.environ["SMTP_SERVER"]
SMTP_PORT = int(os.environ["SMTP_PORT"])
SMTP_USERNAME = os.environ["SMTP_USERNAME"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
SMTP_FROM_EMAIL = os.environ["SMTP_FROM_EMAIL"]
SMTP_FROM_NAME = os.environ["SMTP_FROM_NAME"]

# Temporary single-recipient (until subscriber logic is expanded)
NOTIFY_EMAIL = os.environ["NOTIFY_EMAIL"]

# =========================
# Download Twilio Recording
# =========================

print(f"Downloading recording: {TWILIO_RECORDING_URL}")

response = requests.get(
    f"{TWILIO_RECORDING_URL}.wav",
    auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
    timeout=30,
)
response.raise_for_status()

with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
    f.write(response.content)
    audio_path = f.name

print("Recording downloaded")

# =========================
# Transcribe with Whisper
# =========================

with open(audio_path, "rb") as audio_file:
    transcription = openai.Audio.transcribe(
        model="whisper-1",
        file=audio_file,
    )

text = transcription["text"].strip()
print("Transcription complete")

# =========================
# Google Sheets Append
# =========================

creds = service_account.Credentials.from_service_account_info(
    eval(GOOGLE_SERVICE_ACCOUNT_JSON),
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
)

service = build("sheets", "v4", credentials=creds)
sheet = service.spreadsheets()

now = datetime.now()

row = [
    now.strftime("%Y-%m-%d"),   # Date
    now.strftime("%H:%M:%S"),   # Time
    "",                         # source_call_sid (future)
    "",                         # colors_detected (future)
    "",                         # confidence (future)
    text,                       # transcription
]

sheet.values().append(
    spreadsheetId=GOOGLE_SHEET_ID,
    range="DailyTranscriptions!A:F",
    valueInputOption="RAW",
    body={"values": [row]},
).execute()

print("Google Sheet updated successfully")

# =========================
# Send Email Notification
# =========================

subject = "New Daily Transcription"
body = f"""
A new transcription has been recorded.

Date: {now.strftime("%Y-%m-%d")}
Time: {now.strftime("%H:%M:%S")}

Transcription:
{text}
"""

message = MIMEMultipart()
message["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
message["To"] = NOTIFY_EMAIL
message["Subject"] = subject

message.attach(MIMEText(body, "plain"))

try:
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(message)

    print("Email notification sent successfully")

except Exception as e:
    print(f"Email sending failed: {e}")
