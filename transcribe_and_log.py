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

# Email / SMTP
SMTP_SERVER = os.environ["SMTP_SERVER"]
SMTP_PORT = int(os.environ["SMTP_PORT"])
SMTP_USERNAME = os.environ["SMTP_USERNAME"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
SMTP_FROM_EMAIL = os.environ["SMTP_FROM_EMAIL"]
SMTP_FROM_NAME = os.environ["SMTP_FROM_NAME"]

# =========================
# Helper: normalize transcription
# =========================

def clean_transcription(text: str) -> str:
    text = text.strip()

    replacements = {
        "color gold": "color code",
        "color-goal": "color code",
        "color goal": "color code",
        "color-gold": "color code",
    }

    lowered = text.lower()
    for bad, good in replacements.items():
        lowered = lowered.replace(bad, good)

    stop_phrase = "you must report to drug screen."
    if stop_phrase in lowered:
        lowered = lowered.split(stop_phrase)[0] + stop_phrase

    # Capitalize first letter only (safe, non-destructive)
    return lowered.capitalize()

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

raw_text = transcription["text"]
text = clean_transcription(raw_text)

print("Transcription complete")

# =========================
# Google Sheets Setup
# =========================

creds = service_account.Credentials.from_service_account_info(
    eval(GOOGLE_SERVICE_ACCOUNT_JSON),
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
)

service = build("sheets", "v4", credentials=creds)
sheet = service.spreadsheets()

now = datetime.now()

# =========================
# Append to DailyTranscriptions
# =========================

row = [
    now.strftime("%Y-%m-%d"),
    now.strftime("%H:%M:%S"),
    "",
    "",
    "",
    text,
]

sheet.values().append(
    spreadsheetId=GOOGLE_SHEET_ID,
    range="DailyTranscriptions!A:F",
    valueInputOption="RAW",
    body={"values": [row]},
).execute()

print("DailyTranscriptions updated")

# =========================
# Fetch Active Subscribers
# =========================

subscriber_result = sheet.values().get(
    spreadsheetId=GOOGLE_SHEET_ID,
    range="Subscribers!A2:G",
).execute()

rows = subscriber_result.get("values", [])

active_emails = []

for row in rows:
    if len(row) < 5:
        continue

    email = row[1].strip()
    active_flag = row[4].strip().upper()

    if email and active_flag == "YES":
        active_emails.append(email)

print(f"Active subscribers: {active_emails}")

# =========================
# Send Email to Active Subscribers
# =========================

if active_emails:
    subject = "Daily Color Code Announcement – Powered by ColorCodely!"

    formatted_date = now.strftime("%A, %m/%d/%Y")
    formatted_time = now.strftime("%I:%M %p CST").lstrip("0")

    body = f"""Daily Color Code Announcement - Powered by ColorCodely!

TESTING LOCATION: City of Huntsville, AL Municipal Court - Probation Office
RECORDED LINE: 256-427-7808

DATE: {formatted_date}
TIME: {formatted_time}

RECORDING:
{text}

Stay accountable, stay informed, and good luck on your journey!
"""

    message = MIMEMultipart()
    message["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    message["To"] = ", ".join(active_emails)
    message["Subject"] = subject

    message.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)

        print("Email sent to active subscribers")

    except Exception as e:
        print(f"Email sending failed: {e}")

else:
    print("No active subscribers found — no email sent")
