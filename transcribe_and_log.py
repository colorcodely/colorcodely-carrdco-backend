import os
import logging
import json
from datetime import datetime

import openai
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import requests

# ======================================================
# Logging
# ======================================================

logging.basicConfig(level=logging.INFO)

# ======================================================
# Environment
# ======================================================

def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

OPENAI_API_KEY = require_env("OPENAI_API_KEY")
GOOGLE_SERVICE_ACCOUNT_JSON = require_env("GOOGLE_SERVICE_ACCOUNT_JSON")
GOOGLE_SHEET_ID = require_env("GOOGLE_SHEET_ID")

openai.api_key = OPENAI_API_KEY

# ======================================================
# Google Sheets Setup
# ======================================================

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds = Credentials.from_service_account_info(
    json.loads(GOOGLE_SERVICE_ACCOUNT_JSON),
    scopes=SCOPES,
)

gc = gspread.authorize(creds)
spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)

# ======================================================
# Testing Center → Sheet Mapping (LOCKED)
# ======================================================

SHEET_MAP = {
    "AL_HSV_Municipal_Court": "DailyTranscriptions",
    "AL_HSV_MCOAS": "MCOAS_DailyTranscriptions",
    "AL_MORGANCOUNTY": "AL_MorganCounty_DailyTranscriptions",
}

# ======================================================
# Helpers
# ======================================================

def download_recording(recording_url: str, filename: str):
    logging.info(f"Downloading recording: {recording_url}")
    r = requests.get(f"{recording_url}.wav", auth=(
        os.environ["TWILIO_ACCOUNT_SID"],
        os.environ["TWILIO_AUTH_TOKEN"],
    ))
    r.raise_for_status()

    with open(filename, "wb") as f:
        f.write(r.content)

def transcribe_audio(filepath: str) -> str:
    logging.info("Transcribing audio with OpenAI")
    with open(filepath, "rb") as audio_file:
        transcript = openai.Audio.transcribe(
            model="whisper-1",
            file=audio_file,
        )
    return transcript["text"]

# ======================================================
# Main Entry (GitHub Action)
# ======================================================

def main():
    payload = json.loads(os.environ["GITHUB_EVENT_PAYLOAD"])

    recording_url = payload["recording_url"]
    call_sid = payload.get("call_sid", "")
    testing_center = payload["testing_center"]

    if testing_center not in SHEET_MAP:
        raise RuntimeError(f"Unknown testing center: {testing_center}")

    sheet_name = SHEET_MAP[testing_center]
    sheet = spreadsheet.worksheet(sheet_name)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    audio_file = f"/tmp/{call_sid}.wav"

    download_recording(recording_url, audio_file)
    transcription = transcribe_audio(audio_file)

    logging.info(f"[{testing_center}] Writing to sheet: {sheet_name}")

    sheet.append_row([
        timestamp.split(" ")[0],      # date
        timestamp.split(" ")[1],      # time
        call_sid,                     # source_call_sid
        "",                            # colors_detected (future)
        "",                            # confidence (future)
        transcription,                # transcription
    ], value_input_option="USER_ENTERED")

    logging.info("Transcription logged successfully")

# ======================================================
# Run
# ======================================================

if __name__ == "__main__":
    main()
