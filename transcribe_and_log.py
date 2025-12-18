import os
import re
import tempfile
import requests
import datetime
import logging
import openai
import gspread
from google.oauth2.service_account import Credentials

from notification_templates import (
    color_day_notification,
    no_color_day_notification
)

# =========================
# Logging
# =========================

logging.basicConfig(level=logging.INFO)

# =========================
# Environment Variables
# =========================

openai.api_key = os.environ["OPENAI_API_KEY"]

GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_CREDS_JSON = os.environ["GOOGLE_CREDS_JSON"]

SMTP_FROM_EMAIL = os.environ["SMTP_FROM_EMAIL"]
SMTP_API_URL = os.environ["SMTP_API_URL"]
SMTP_API_KEY = os.environ["SMTP_API_KEY"]

TWILIO_RECORDING_URL = os.environ["TWILIO_RECORDING_URL"]

# =========================
# Constants
# =========================

TESTING_CENTER_NAME = "City of Huntsville, AL Municipal Court Probation Office"
ANNOUNCEMENT_PHONE = "256-427-7808"

COLOR_KEYWORDS = [
    "you must report to drug screen",
    "if your color is called"
]

# =========================
# Google Sheets Setup
# =========================

creds_dict = eval(GOOGLE_CREDS_JSON)

scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gc = gspread.authorize(credentials)

sheet = gc.open_by_key(GOOGLE_SHEET_ID)
log_sheet = sheet.worksheet("Log")
subscribers_sheet = sheet.worksheet("Subscribers")

# =========================
# Helpers
# =========================

def normalize_text(text):
    return re.sub(r"\s+", " ", text.lower()).strip()


def detect_color_day(transcription):
    normalized = normalize_text(transcription)
    return any(keyword in normalized for keyword in COLOR_KEYWORDS)


def extract_colors(transcription):
    match = re.search(
        r"are (.+?)\. if your color is called",
        transcription.lower()
    )
    if match:
        return match.group(1).strip()
    return transcription.strip()


def get_active_subscribers():
    rows = subscribers_sheet.get_all_records()
    return [
        row["email"]
        for row in rows
        if row.get("active", "").strip().upper() == "YES"
    ]


def send_email(subject, body, recipients):
    payload = {
        "from": SMTP_FROM_EMAIL,
        "to": recipients,
        "subject": subject,
        "text": body
    }

    headers = {
        "Authorization": f"Bearer {SMTP_API_KEY}",
        "Content-Type": "application/json"
    }

    r = requests.post(SMTP_API_URL, json=payload, headers=headers)
    logging.info(f"Email send response: {r.status_code}")


# =========================
# Main
# =========================

def main():
    logging.info("Downloading recording")

    audio_response = requests.get(f"{TWILIO_RECORDING_URL}.wav", auth=(
        os.environ["TWILIO_ACCOUNT_SID"],
        os.environ["TWILIO_AUTH_TOKEN"]
    ))

    audio_response.raise_for_status()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
        f.write(audio_response.content)
        audio_path = f.name

    logging.info("Transcribing audio")

    with open(audio_path, "rb") as audio_file:
        transcription = openai.Audio.transcribe(
            model="whisper-1",
            file=audio_file
        )["text"].strip()

    # -------------------------
    # Loop cutoff
    # -------------------------

    cutoff_phrase = "if your color is called"
    idx = transcription.lower().find(cutoff_phrase)
    if idx != -1:
        transcription = transcription[: idx + len(cutoff_phrase) + 1]

    transcription = transcription.strip()

    # -------------------------
    # Detect type
    # -------------------------

    is_color_day = detect_color_day(transcription)

    now = datetime.datetime.now()
    date_str = now.strftime("%A %m/%d/%Y")
    time_str = now.strftime("%H:%M:%S")

    # -------------------------
    # Log to Sheet
    # -------------------------

    log_sheet.append_row([
        now.date().isoformat(),
        time_str,
        transcription
    ])

    # -------------------------
    # Build Notification
    # -------------------------

    if is_color_day:
        color_codes = extract_colors(transcription)
        subject, body = color_day_notification(
            date_str=date_str,
            testing_center=TESTING_CENTER_NAME,
            announcement_phone=ANNOUNCEMENT_PHONE,
            color_codes=color_codes
        )
    else:
        subject, body = no_color_day_notification(
            date_str=date_str,
            testing_center=TESTING_CENTER_NAME,
            announcement_phone=ANNOUNCEMENT_PHONE
        )

    # -------------------------
    # Send Emails
    # -------------------------

    recipients = get_active_subscribers()
    if recipients:
        send_email(subject, body, recipients)
        logging.info(f"Sent email to {len(recipients)} subscribers")
    else:
        logging.warning("No active subscribers found")


if __name__ == "__main__":
    main()
