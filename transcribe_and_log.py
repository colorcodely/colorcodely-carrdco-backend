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

TESTING_CENTER = os.environ["TESTING_CENTER"]

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

# Optional: if you add this secret later, we'll use it for the visible "To" line.
# Otherwise we default to SMTP_FROM_EMAIL.
PUBLIC_TO_EMAIL = os.environ.get("PUBLIC_TO_EMAIL", SMTP_FROM_EMAIL)

# =========================
# Center Config
# =========================

CENTER_CONFIG = {
    "AL_HSV_Municipal_Court": {
        "location": "City of Huntsville, AL Municipal Court – Probation Office",
        "phone": "256-427-7808",
        "sheet": "DailyTranscriptions",
    },
    "AL_HSV_MCOAS": {
        "location": "Madison County Office of Alternative Sentencing",
        "phone": "256-533-8943",
        "sheet": "MCOAS_DailyTranscriptions",
    },
}

if TESTING_CENTER not in CENTER_CONFIG:
    raise ValueError(f"Unknown TESTING_CENTER: {TESTING_CENTER}")

cfg = CENTER_CONFIG[TESTING_CENTER]

# =========================
# Helper: transcription cleanup
# =========================

def clean_transcription(text: str) -> str:
    text = text.lower().strip()

    fixes = {
        "color coat": "color code",
        "color gold": "color code",
        "color goal": "color code",
        "drug street": "drug screen",
    }
    for bad, good in fixes.items():
        text = text.replace(bad, good)

    # Basic cleanup
    text = text.strip()
    if text and not text.endswith("."):
        text += "."

    # Capitalize first letter
    return text[:1].upper() + text[1:] if text else text

# =========================
# Download Twilio Recording
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
# Time (CST/CDT safe)
# =========================

now = datetime.now(tz=ZoneInfo("UTC")).astimezone(ZoneInfo("America/Chicago"))

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
    range=f"{cfg['sheet']}!A:F",
    valueInputOption="RAW",
    body={"values": [row]},
).execute()

# =========================
# Active Subscribers (filtered by testing center)
# =========================

result = sheet.values().get(
    spreadsheetId=GOOGLE_SHEET_ID,
    range="Subscribers!A2:G",
).execute()

rows = result.get("values", [])

active_emails = []
for r in rows:
    # Expected columns:
    # A full_name, B email, C cell_number, D testing_center, E active, F created_at, G ...
    if len(r) < 5:
        continue
    email = (r[1] or "").strip()
    center = (r[3] or "").strip()
    active = (r[4] or "").strip().upper()

    if email and active == "YES" and center == TESTING_CENTER:
        active_emails.append(email)

# =========================
# Email Notification (BCC)
# =========================

if active_emails:
    subject = "📣 Daily Color Code Announcement - Powered by ColorCodely!"

    body = f"""📣 Daily Color Code Announcement - Powered by ColorCodely!

🏛️ TESTING LOCATION: {cfg['location']}
☎️ RECORDED LINE: {cfg['phone']}

📅 DATE: {now.strftime("%A, %m/%d/%Y")}
🕒 TIME: {now.strftime("%I:%M %p CST")}

🎤 RECORDING:
{text}

👍 Stay accountable, stay informed, and good luck on your journey!

You are receiving this email because you subscribed to ColorCodely alerts.

ColorCodely
📧 colorcodely@gmail.com
🌐 https://colorcodely.carrd.co
🚀 Huntsville, AL
"""

    msg = MIMEMultipart()
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"

    # Show only a single public address in the email header:
    msg["To"] = PUBLIC_TO_EMAIL

    # Put all recipients in BCC (hidden)
    msg["Bcc"] = ", ".join(active_emails)

    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    # IMPORTANT: pass the actual recipients list to sendmail
    # so all BCC recipients receive the email.
    recipients = [PUBLIC_TO_EMAIL] + active_emails

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM_EMAIL, recipients, msg.as_string())
