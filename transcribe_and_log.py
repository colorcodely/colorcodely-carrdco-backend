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
# ENV
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

PUBLIC_TO_EMAIL = SMTP_FROM_EMAIL

# =========================
# CENTER CONFIG
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
    "AL_MORGANCOUNTY": {
        "location": "Morgan County Court Referral Office",
        "phone": "256-560-6042",
        "sheet": "AL_MorganCounty_DailyTranscriptions",
    },
}

cfg = CENTER_CONFIG[TESTING_CENTER]

# =========================
# CLEAN TRANSCRIPTION
# =========================

def clean_transcription(text: str) -> str:
    text = text.lower().strip()

    replacements = {
        "color gold": "color code",
        "color goal": "color code",
        "color coat": "color code",
        "drug street": "drug screen",
    }

    for bad, good in replacements.items():
        text = text.replace(bad, good)

    stop_phrase = "you must report to drug screen."
    if stop_phrase in text:
        text = text.split(stop_phrase)[0] + stop_phrase

    sentences, seen = [], set()
    for s in text.split("."):
        s = s.strip()
        if not s:
            continue
        s = s.capitalize()
        if s not in seen:
            sentences.append(s)
            seen.add(s)

    text = ". ".join(sentences)
    if not text.endswith("."):
        text += "."

    for d in ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]:
        text = text.replace(d.lower(), d)
    for m in ["January","February","March","April","May","June","July","August","September","October","November","December"]:
        text = text.replace(m.lower(), m)

    return text

# =========================
# DOWNLOAD RECORDING
# =========================

resp = requests.get(
    f"{TWILIO_RECORDING_URL}.wav",
    auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
    timeout=30,
)
resp.raise_for_status()

with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
    f.write(resp.content)
    audio_path = f.name

# =========================
# TRANSCRIBE
# =========================

with open(audio_path, "rb") as audio:
    result = openai.Audio.transcribe("whisper-1", audio)

text = clean_transcription(result["text"])

# =========================
# TIME
# =========================

now = datetime.now(tz=ZoneInfo("UTC")).astimezone(
    ZoneInfo("America/Chicago")
)

# =========================
# SHEETS
# =========================

creds = service_account.Credentials.from_service_account_info(
    eval(GOOGLE_SERVICE_ACCOUNT_JSON),
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
)

service = build("sheets", "v4", credentials=creds)
sheet = service.spreadsheets()

sheet.values().append(
    spreadsheetId=GOOGLE_SHEET_ID,
    range=f"{cfg['sheet']}!A:F",
    valueInputOption="RAW",
    body={"values": [[
        now.strftime("%Y-%m-%d"),
        now.strftime("%H:%M:%S"),
        "", "", "", text
    ]]},
).execute()

# =========================
# SUBSCRIBERS
# =========================

rows = sheet.values().get(
    spreadsheetId=GOOGLE_SHEET_ID,
    range="Subscribers!A2:G",
).execute().get("values", [])

emails = [
    r[1].strip()
    for r in rows
    if len(r) >= 5
    and r[1].strip()
    and r[3].strip() == TESTING_CENTER
    and r[4].strip().upper() == "YES"
]

# =========================
# EMAIL (BCC)
# =========================

if emails:
    msg = MIMEMultipart()
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    msg["To"] = PUBLIC_TO_EMAIL
    msg["Bcc"] = ", ".join(emails)
    msg["Subject"] = "📣 Daily Color Code Announcement - Powered by ColorCodely!"

    body = f"""📣 Daily Color Code Announcement - Powered by ColorCodely!

🏛️ TESTING LOCATION: {cfg['location']}
☎️ RECORDED LINE: {cfg['phone']}

📅 DATE: {now.strftime("%A, %m/%d/%Y")}
🕒 TIME: {now.strftime("%I:%M %p CST")}

🎤 RECORDING:
{text}

👍 Stay accountable, stay informed, and good luck on your journey!

You are receiving this email because you subscribed to ColorCodely alerts.
"""

    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(
            SMTP_FROM_EMAIL,
            [PUBLIC_TO_EMAIL] + emails,
            msg.as_string()
        )
