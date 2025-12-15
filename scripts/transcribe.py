import os
import requests
import tempfile
from openai import OpenAI
from google.oauth2 import service_account
from googleapiclient.discovery import build

RECORDING_URL = os.environ["RECORDING_URL"]
TWILIO_SID = os.environ["TWILIO_SID"]
TWILIO_AUTH = os.environ["TWILIO_AUTH"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL")

client = OpenAI(api_key=OPENAI_API_KEY)

print(f"Downloading recording: {RECORDING_URL}")

auth = (TWILIO_SID, TWILIO_AUTH)
response = requests.get(f"{RECORDING_URL}.wav", auth=auth)
response.raise_for_status()

with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
    f.write(response.content)
    audio_path = f.name

with open(audio_path, "rb") as audio_file:
    transcript = client.audio.transcriptions.create(
        file=audio_file,
        model="gpt-4o-transcribe"
    )

text = transcript.text
print("Transcription complete")

# --- Google Sheets ---
creds = service_account.Credentials.from_service_account_file(
    "google_service_account.json",
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)

service = build("sheets", "v4", credentials=creds)
sheet = service.spreadsheets()

sheet.values().append(
    spreadsheetId=GOOGLE_SHEET_ID,
    range="Sheet1!A:B",
    valueInputOption="RAW",
    body={"values": [[text]]}
).execute()

print("Google Sheet updated")

# --- Optional Email ---
if NOTIFY_EMAIL:
    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg.set_content(text)
    msg["Subject"] = "Daily Call Transcription"
    msg["From"] = NOTIFY_EMAIL
    msg["To"] = NOTIFY_EMAIL

    with smtplib.SMTP("localhost") as s:
        s.send_message(msg)

    print("Notification email sent")
