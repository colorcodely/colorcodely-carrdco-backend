import os
import re
import requests
import datetime
import logging
import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI

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

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_CREDS_JSON = os.environ["GOOGLE_CREDS_JSON"]

SMTP_FROM_EMAIL = os.environ["SMTP_FROM_EMAIL"]
SMTP_API_URL = os.environ["SMTP_API_URL"]
SMTP_API_KEY = os.environ["SMTP_API_KEY"]

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
# OpenAI Client
# =========================

openai_client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# Helpers
# =========================

def normalize_text(text):
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def detect_color_day(transcription):
    normalized = normalize_text(transcription)
    return any(keyword in normalized for keyword in COLOR_KEYWORDS)


def extract_colors(transcription):
    """
    Attempts to extract just the color list portion.
    Falls back to cleaned transcription if uncertain.
    """

    match = re.search(
        r"are (.+?)\. if your color is called",
        transcription.lower()
    )

    if match:
        return match.group(1).strip()

    return transcription.strip()


def get_active_subscribers():
    records = subscribers_sheet.get_all_records()
    return [
        row["email"]
        for row in records
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

    response = requests.post(SMTP_API_URL, json=payload, headers=headers)

    logging.info(f"Email send status: {response.status_code}")


# =========================
# Main Entry Point
# =========================

def main(recording_url, call_sid):
    logging.info("Starting transcription workflow")

    # -------------------------
    # Transcribe audio
    # -------------------------

    transcription_response = openai_client.audio.transcriptions.create(
        file=recording_url,
        model="gpt-4o-transcribe"
    )

    transcription = transcription_response.text.strip()
    logging.info("Raw transcription received")

    # -------------------------
    # De-duplicate looping audio
    # -------------------------

    cutoff_phrase = "if your color is called"
    cutoff_index = transcription.lower().find(cutoff_phrase)

    if cutoff_index != -1:
        transcription = transcription[: cutoff_index + len(cutoff_phrase) + 1]

    transcription = transcription.strip()

    # -------------------------
    # Detect color vs no-color day
    # -------------------------

    is_color_day = detect_color_day(transcription)

    today = datetime.datetime.now().strftime("%A %m/%d/%Y")
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")

    # -------------------------
    # Log to Google Sheet
    # -------------------------

    log_sheet.append_row([
        datetime.date.today().isoformat(),
        timestamp,
        call_sid,
        transcription
    ])

    # -------------------------
    # Build notification
    # -------------------------

    if is_color_day:
        color_codes = extract_colors(transcription)

        subject, body = color_day_notification(
            date_str=today,
            testing_center=TESTING_CENTER_NAME,
            announcement_phone=ANNOUNCEMENT_PHONE,
            color_codes=color_codes
        )
    else:
        subject, body = no_color_day_notification(
            date_str=today,
            testing_center=TESTING_CENTER_NAME,
            announcement_phone=ANNOUNCEMENT_PHONE
        )

    # -------------------------
    # Send emails
    # -------------------------

    recipients = get_active_subscribers()

    if recipients:
        send_email(subject, body, recipients)
        logging.info(f"Email sent to {len(recipients)} subscribers")
    else:
        logging.warning("No active subscribers found")

    logging.info("Workflow complete")
