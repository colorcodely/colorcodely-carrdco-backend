import os
import json
import smtplib
from email.message import EmailMessage
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

# =========================
# Environment variables
# =========================
GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_CREDS_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]

SMTP_SERVER = os.environ["SMTP_SERVER"]
SMTP_PORT = int(os.environ["SMTP_PORT"])
SMTP_USERNAME = os.environ["SMTP_USERNAME"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
SMTP_FROM_EMAIL = os.environ["SMTP_FROM_EMAIL"]
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "Color Codely")

# =========================
# Google Sheets setup
# =========================
creds_info = json.loads(GOOGLE_CREDS_JSON)
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
gc = gspread.authorize(creds)

sheet = gc.open_by_key(GOOGLE_SHEET_ID)

subscribers_ws = sheet.worksheet("Subscribers")
transcriptions_ws = sheet.worksheet("DailyTranscriptions")

# =========================
# Get latest transcription
# =========================
rows = transcriptions_ws.get_all_records()

if not rows:
    raise RuntimeError("No transcription rows found.")

latest = rows[-1]

transcription_text = latest.get("transcription", "").strip()
date = latest.get("date", "")
time = latest.get("time", "")

if not transcription_text:
    raise RuntimeError("Latest transcription is empty.")

# =========================
# Get subscriber emails
# =========================
subscriber_rows = subscribers_ws.get_all_records()
emails = [
    row["email"].strip()
    for row in subscriber_rows
    if row.get("email")
]

if not emails:
    raise RuntimeError("No subscriber emails found.")

# =========================
# Email body
# =========================
subject = f"Daily Color Code Update – {date}"

body = f"""
Hello,

Here is the latest Color Code transcription.

Date: {date}
Time: {time}

------------------------------------
{transcription_text}
------------------------------------

This message was sent automatically.
"""

# =========================
# Send emails
# =========================
with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
    server.starttls()
    server.login(SMTP_USERNAME, SMTP_PASSWORD)

    for recipient in emails:
        msg = EmailMessage()
        msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.set_content(body)

        server.send_message(msg)
        print(f"Email sent to {recipient}")

print("All emails sent successfully.")
