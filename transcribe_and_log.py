import os
import requests
import tempfile
from datetime import datetime

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

transcription_text = transcription["text"].strip()
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
# Prepare Row (DailyTranscriptions)
# date | time | source_call_sid | colors_detected | confidence | transcription
# =========================
now = datetime.now()

row = [
    now.strftime("%Y-%m-%d"),
    now.strftime("%H:%M:%S"),
    "",
    "",
    "",
    transcription_text,
]

sheet.values().append(
    spreadsheetId=GOOGLE_SHEET_ID,
    range="DailyTranscriptions!A:F",
    valueInputOption="RAW",
    body={"values": [row]},
).execute()

print("Google Sheet updated successfully")
