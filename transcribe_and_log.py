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
SMTP_FROM_NAME = os.environ["SMTP_FROM_NAME"]

# =========================
# Helper: transcription cleanup
# =========================

def clean_transcription(text: str) -> str:
    text = text.lower().strip()

    replacements = {
        "color gold": "color code",
        "color-goal": "color code",
        "color goal": "color code",
        "color-gold": "color code",
        "city of huntsville": "City of Huntsville",
        "huntsville": "Huntsville",
    }

    for bad, good in replacements.items():
        text = text.replace(bad, good)

    stop_phrase = "you must report to drug screen."
    if stop_phrase in text:
        text = text.split(stop_phrase)[0] + stop_phrase

    # Capitalize sentences
    sentences = [s.strip().capitalize() for s in text.split(".") if s.strip()]
    text = ". ".join(sentences) + "."

    # Capitalize days and months
    days = [
        "monday", "tuesday", "wednesday",
        "thursday", "friday", "saturday", "sunday"
    ]
    months = [
        "january", "february", "march", "april",
        "may", "june", "july", "august",
        "september", "october", "november", "december"
    ]

    for d in days:
        text = text.replace(d, d.capitalize())

    for m in months:
        text = text.replace(m, m.capitalize())

    return text.strip()

# =========================
# Download Twilio recording
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
# Transcribe with Whisper
# =========================

with open(audio_path, "rb") as audio_file:
    transcription = openai.Audio.transcribe(
        model="whisper-1",
        file=audio_file,
    )

raw_text = transcription["text"]
text = clean_transcription(raw_text)

# =========================
# Time (America/Chicago)
# =========================

now = datetime.now(tz=ZoneInfo("UTC")).astimezone(
    ZoneInfo("America/Chicago")
)

# =========================
# Google Sheets
# =========================

creds = service_account.Credentials.from_service_account_info(
    eval(GOOGLE_SERVICE_ACCOUNT_JSON),
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
)

service = build("sheets", "v4", credentials=creds)
sheet = service.spreadsheets()

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

# =========================
# Fetch active subscribers
# =========================

result = sheet.values().get(
    spreadsheetId=GOOGLE_SHEET_ID,
    range="Subscribers!A2:G",
).execute()

rows = result.get("values", [])

active_emails = [
    r[1].strip()
    for r in rows
    if len(r) >= 5 and r[1].strip() and r[4].strip().upper() == "YES"
]

# =========================
# Send Email (BCC only)
# =========================

if active_emails:
    subject = "Daily Color Code Announcement - Powered by ColorCodely!"

    body = f"""📣 Daily Color Code Announcement - Powered by ColorCodely!

📍 TESTING LOCATION:  City of Huntsville, AL Municipal Court - Probation Office
☎️ RECORDED LINE:     256-427-7808

📅 DATE:  {now.strftime("%A, %m/%d/%Y")}
🕒 TIME:  {now.strftime("%I:%M %p CST")}

🎤 RECORDING:  {text}

👍 Stay accountable, stay informed, and good luck on your journey!
"""

    msg = MIMEMultipart()
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    msg["To"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    msg["Bcc"] = ", ".join(active_emails)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)
