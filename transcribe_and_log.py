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

cfg = CENTER_CONFIG[TESTING_CENTER]

def clean_transcription(text: str) -> str:
    fixes = {
        "color coat": "color code",
        "color gold": "color code",
        "drug street": "drug screen",
    }
    text = text.lower()
    for k, v in fixes.items():
        text = text.replace(k, v)
    return text.capitalize()

# Download recording
response = requests.get(
    f"{TWILIO_RECORDING_URL}.wav",
    auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
)
response.raise_for_status()

with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
    f.write(response.content)
    audio_path = f.name

with open(audio_path, "rb") as audio_file:
    transcription = openai.Audio.transcribe("whisper-1", audio_file)

text = clean_transcription(transcription["text"])

now = datetime.now(tz=ZoneInfo("America/Chicago"))

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
    body={"values": [[now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), "", "", "", text]]},
).execute()

subs = sheet.values().get(
    spreadsheetId=GOOGLE_SHEET_ID,
    range="Subscribers!A2:G",
).execute().get("values", [])

emails = [
    r[1]
    for r in subs
    if r[4].upper() == "YES" and r[3] == TESTING_CENTER
]

if emails:
    msg = MIMEMultipart()
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    msg["To"] = ", ".join(emails)
    msg["Subject"] = "📣 Daily Color Code Announcement - Powered by ColorCodely!"

    msg.attach(MIMEText(f"""
🏛️ TESTING LOCATION: {cfg['location']}
☎️ RECORDED LINE: {cfg['phone']}

📅 DATE: {now.strftime('%A, %m/%d/%Y')}
🕒 TIME: {now.strftime('%I:%M %p CST')}

🎤 RECORDING:
{text}
""", "plain"))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as s:
        s.starttls()
        s.login(SMTP_USERNAME, SMTP_PASSWORD)
        s.send_message(msg)
