import os
import requests
from requests.auth import HTTPBasicAuth

# =========================
# Required Environment Vars
# =========================
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_RECORDING_URL = os.environ["TWILIO_RECORDING_URL"]

# =========================
# Step 1: Download recording
# =========================
print(f"Downloading recording: {TWILIO_RECORDING_URL}")

audio_response = requests.get(
    f"{TWILIO_RECORDING_URL}.wav",
    auth=HTTPBasicAuth(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
    timeout=60
)

audio_response.raise_for_status()

audio_path = "recording.wav"
with open(audio_path, "wb") as f:
    f.write(audio_response.content)

print("Recording downloaded")

# =========================
# Step 2: Send to OpenAI
# =========================
print("Sending audio to OpenAI (whisper-1)")

openai_response = requests.post(
    "https://api.openai.com/v1/audio/transcriptions",
    headers={
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    },
    files={
        "file": ("recording.wav", open(audio_path, "rb"), "audio/wav")
    },
    data={
        "model": "whisper-1",
        "response_format": "text"
    },
    timeout=120
)

openai_response.raise_for_status()

transcription_text = openai_response.text.strip()

print("Transcription complete")
print("----- TRANSCRIPTION START -----")
print(transcription_text)
print("----- TRANSCRIPTION END -----")

# =========================
# Step 3: Persist / forward
# =========================
# At this point:
# - transcription_text contains the final transcript
# - You can log it, store it, or send it to Google Sheets here
# - Leaving unchanged per current pipeline

