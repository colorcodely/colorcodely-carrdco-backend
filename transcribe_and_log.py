import os
import requests
import tempfile
import openai
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- Environment variables ---
openai.api_key = os.environ["OPENAI_API_KEY"]

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_RECORDING_URL = os.environ["TWILIO_RECORDING_URL"]

GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]

print(f"Downloading recording: {TWILIO_RECORDING_URL}")

# --- Download Twilio recording ---
response = requests.get(
    f"{TWILIO_RECORDING_URL}.wav",
    auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
)
response.raise_for_status()

with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
    f.write(response.content)
    audio_path = f.name

print("Recording downloaded")

# --- Transcription (NO OpenAI client object) ---
with open(audio_path, "rb") as audio_file:
    transcription = openai.audio.transcriptions.create(
        file=audio_file,
        model="gpt-4o-transcribe"
    )

text = transcription.text
print("Transcription complete")

# --- Google Sheets ---
creds = service_account.Credentials.from_service_account_info(
    eval(GOOGLE_SERVICE_ACCOUNT_JSON),
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)

service = build("sheets", "v4", credentials=creds)

service.spreadsheets().values().append(
    spreadsheetId=GOOGLE_SHEET_ID,
    range="Sheet1!A:A",
    valueInputOption="RAW",
    body={"values": [[text]]}
).execute()

print("Google Sheet updated successfully")
