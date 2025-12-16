import os
import requests
import tempfile
from datetime import datetime

from openai import OpenAI
from google.oauth2 import service_account
from googleapiclient.discovery import build

# =========================
# Environment Variables
# =========================
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_RECORDING_URL = os.environ["TWILIO_RECORDING_URL"]

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]

# =========================
# OpenAI Client
# =========================
client = OpenAI(api_key=OPENAI_API_KEY)

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
    transcription_response = client.audio.transcriptions.create(
        file=audio_file,
        model="whisper-1",
    )

transcription_text = transcription_response.text.strip()
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

# =========================
# Prepare Row (matches your headers)
# Sheet: DailyTranscriptions
# Columns:
# date | time | source_call_sid | colors_detected | confidence | transcription
# =========================
now = datetime.now()

row = [
    now.strftime("%Y-%m-%d"),     # date
    now.strftime("%H:%M:%S"),     # time
    "",                           # source_call_sid (can fill later)
    "",                           # colors_detected (future logic)
    "",                           # confidence (future logic)
    transcription_text,           # transcription
]

sheet.values().append(
    spreadsheetId=GOOGLE_SHEET_ID,
    range="DailyTranscriptions!A:F",
    valueInputOption="RAW",
    body={"values": [row]},
).execute()

print("Google Sheet updated successfully")
