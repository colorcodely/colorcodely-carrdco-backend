import os
import requests
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo
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
    """
    - Normalizes common Whisper errors (gold/goal → code)
    - Stops at 'you must report to drug screen.'
    - Capitalizes each sentence conservatively
    """
    lowered = text.lower().strip()

    replacements = {
        "color gold": "color code",
        "color-goal": "color code",
        "color goal": "color code",
        "color-gold": "color code",
    }

    for bad, good in replacements.items():
        lowered = lowered.replace(bad, good)

    stop_phrase = "you must report to drug screen."
    if stop_phrase in lowered:
        lowered = lowered.split(stop_phrase)[0] + stop_phrase

    # Capitalize each sentence safely
    sentences = lowered.split(". ")
    sentences = [s.capitalize() for s in sentences if s]

    return ". ".join(sentences).strip()

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
# Time (Correct CST/CDT)
# =========================

now = datetime.now(tz=ZoneInfo("UTC")).astimezone(ZoneInfo("America/Chicago"))

# =========================
# Google Sheets Setup
# =========================

creds = service_account.Credentials.from_service_account_info(
    eval(GOOGLE_SERVICE_ACCOUNT_JSON),
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
)

service = build("sheets", "v4", credentials=creds)
sheet = service.spreadsheets()

# =========================
# Append to DailyTranscriptions
# =========================

row = [
    now.strftime("%Y-%m-%d"),   # date
    now.strftime("%H:%M:%S"),   # time (CST/CDT)
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
    subject = "Daily Color Code Announcement - Powered by ColorCodely!"

    body = f"""Daily Color Code Announcement - Powered by ColorCodely!

TESTING LOCATION: City of Huntsville, AL Municipal Court - Probation Office
RECORDED LINE: 256-427-7808

DATE: {now.strftime("%A, %m/%d/%Y")}
TIME: {now.strftime("%I:%M %p CST")}

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
