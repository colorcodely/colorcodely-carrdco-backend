import os
import requests
import tempfile
import smtplib
from email.message import EmailMessage
from datetime import datetime

import openai
import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build

# =========================
# Environment Variables
# =========================
openai.api_key = os.environ["OPENAI_API_KEY"]

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_RECORDING_URL = os.environ["TWILIO_RECORDING_URL"]

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]

SMTP_SERVER = os.environ["SMTP_SERVER"]
SMTP_PORT = int(os.environ["SMTP_PORT"])
SMTP_USERNAME = os.environ["SMTP_USERNAME"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
SMTP_FROM_EMAIL = os.environ["SMTP_FROM_EMAIL"]
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "Color Code Alert")

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
# Google Sheets Setup
# =========================
creds = service_account.Credentials.from_service_account_info(
    eval(GOOGLE_SERVICE_ACCOUNT_JSON),
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
)

# Sheets API (for DailyTranscriptions)
service = build("sheets", "v4", credentials=creds)
sheet_api = service.spreadsheets()

# gspread (for Subscribers tab)
gc = gspread.authorize(creds)
spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)

# =========================
# Append DailyTranscriptions
# =========================
now = datetime.now()

row = [
    now.strftime("%Y-%m-%d"),   # date
    now.strftime("%H:%M:%S"),   # time
    "",                         # source_call_sid
    "",                         # colors_detected
    "",                         # confidence
    text,                       # transcription
]

sheet_api.values().append(
    spreadsheetId=GOOGLE_SHEET_ID,
    range="DailyTranscriptions!A:F",
    valueInputOption="RAW",
    body={"values": [row]},
).execute()

print("Google Sheet updated successfully")

# =========================
# Read Subscribers
# =========================
subscribers_ws = spreadsheet.worksheet("Subscribers")
subscribers = subscribers_ws.get_all_records()

emails = [
    row["email"].strip()
    for row in subscribers
    if row.get("email")
]

print(f"Found {len(emails)} subscriber emails")

if not emails:
    print("No subscribers found — skipping email send")
    exit(0)

# =========================
# Send Email
# =========================
msg = EmailMessage()
msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
msg["To"] = ", ".join(emails)
msg["Subject"] = "Daily Color Code Transcription"

msg.set_content(
    f"""
Here is the latest transcription:

{text}

—
This message was sent automatically.
"""
)

with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
    server.starttls()
    server.login(SMTP_USERNAME, SMTP_PASSWORD)
    server.send_message(msg)

print("Email sent successfully to subscribers")
