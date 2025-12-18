import os
import re
import json
import requests
import datetime
from twilio.rest import Client
import gspread
from google.oauth2.service_account import Credentials

# =========================
# ENVIRONMENT VARIABLES
# =========================

TWILIO_SID = os.environ["TWILIO_SID"]
TWILIO_AUTH = os.environ["TWILIO_AUTH"]
TWILIO_RECORDING_URL = os.environ["TWILIO_RECORDING_URL"]

EMAIL_WEBHOOK_URL = os.environ["EMAIL_WEBHOOK_URL"]  # existing, already-working method

GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_CREDS_JSON = os.environ["GOOGLE_CREDS_JSON"]

# =========================
# SETUP CLIENTS
# =========================

twilio_client = Client(TWILIO_SID, TWILIO_AUTH)

creds_dict = json.loads(GOOGLE_CREDS_JSON)
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gc = gspread.authorize(creds)

sheet = gc.open_by_key(GOOGLE_SHEET_ID)
log_sheet = sheet.worksheet("Logs")
subs_sheet = sheet.worksheet("Subscribers")

# =========================
# HELPERS
# =========================

STOP_PHRASE = "you must report to drug screen"

CODE_VARIANTS = [
    "color code",
    "color-code",
    "color gold",
    "color-gold",
    "color goal",
    "color-goal"
]

def normalize_text(text: str) -> str:
    t = text.lower()
    for variant in CODE_VARIANTS:
        t = t.replace(variant, "color code")
    return t

def trim_looping(text: str) -> str:
    idx = text.find(STOP_PHRASE)
    if idx != -1:
        return text[: idx + len(STOP_PHRASE)].strip()
    return text.strip()

def detect_color_day(text: str) -> bool:
    return "are" in text and "," in text

def get_active_emails():
    rows = subs_sheet.get_all_records()
    emails = []
    for r in rows:
        if str(r.get("ACTIVE", "")).strip().upper() == "YES":
            if r.get("EMAIL"):
                emails.append(r["EMAIL"])
    return emails

def send_email(subject, body, recipients):
    payload = {
        "subject": subject,
        "body": body,
        "recipients": recipients
    }
    requests.post(EMAIL_WEBHOOK_URL, json=payload, timeout=10)

# =========================
# MAIN LOGIC
# =========================

print("Downloading recording...")
audio = requests.get(TWILIO_RECORDING_URL, auth=(TWILIO_SID, TWILIO_AUTH))
audio.raise_for_status()

print("Sending audio for transcription...")
transcription = twilio_client.transcriptions.create(
    recording_url=TWILIO_RECORDING_URL
)

raw_text = transcription.transcription_text or ""
normalized = normalize_text(raw_text)
clean_text = trim_looping(normalized)

now = datetime.datetime.now()
date_str = now.strftime("%Y-%m-%d")
time_str = now.strftime("%H:%M:%S")

# =========================
# LOG TO SHEET
# =========================

log_sheet.append_row([
    date_str,
    time_str,
    clean_text
])

# =========================
# EMAIL NOTIFICATION
# =========================

recipients = get_active_emails()

if not recipients:
    print("No active subscribers. Exiting.")
    exit(0)

is_color_day = detect_color_day(clean_text)

if is_color_day:
    subject = "ColorCodely Notification – City of Huntsville, AL"
    body = (
        "🎨 **COLOR CODE NOTIFICATION – Powered by ColorCodely!**\n\n"
        f"📅 **DATE:** {now.strftime('%A %m/%d/%Y')}\n"
        "🏛️ **TESTING CENTER:** City of Huntsville, AL Municipal Court Probation Office\n"
        "📞 **ANNOUNCEMENT PHONE:** (256) 427-7808\n\n"
        f"🎯 **COLOR CODES:**\n{clean_text}"
    )
else:
    subject = "ColorCodely Notice – No Colors Called Today"
    body = (
        "🚫 **NO COLOR DAY – Powered by ColorCodely!**\n\n"
        f"📅 **DATE:** {now.strftime('%A %m/%d/%Y')}\n"
        "🏛️ **TESTING CENTER:** City of Huntsville, AL Municipal Court Probation Office\n\n"
        "The testing center appears to be closed or no colors were announced today.\n"
        "No action is required."
    )

send_email(subject, body, recipients)

print("Transcription logged and notifications sent.")
