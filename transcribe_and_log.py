import os
import requests
import tempfile
from openai import OpenAI
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- Required environment variables ---
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_RECORDING_URL = os.environ["TWILIO_RECORDING_URL"]
GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]

NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL")

# --- OpenAI client (correct for SDK 1.x) ---
client = OpenAI(api_key=OPENAI_API_KEY)

print(f"Downloading recording: {TWILIO_RECORDING_URL}")

# --- Download recording from Twilio ---
response = requests.get(
    f"{TWILIO_RECORDING_URL}.wav",
    auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
)
response.raise_for_status()

with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
    f.write(response.content)
    audio_path = f.name

# --- Transcription ---
with open(audio_path, "rb") as audio_file:
    transcription = client.audio.transcriptions.create(
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
sheet = service.spreadsheets()

sheet.values().append(
    spreadsheetId=GOOGLE_SHEET_ID,
    range="Sheet1!A:A",
    valueInputOption="RAW",
    body={"values": [[text]]}
).execute()

print("Google Sheet updated")

# --- Optional email ---
if NOTIFY_EMAIL:
    from email.message import EmailMessage
    import smtplib

    msg = EmailMessage()
    msg.set_content(text)
    msg["Subject"] = "Daily Call Transcription"
    msg["From"] = NOTIFY_EMAIL
    msg["To"] = NOTIFY_EMAIL

    with smtplib.SMTP("localhost") as s:
        s.send_message(msg)

    print("Notification email sent")
