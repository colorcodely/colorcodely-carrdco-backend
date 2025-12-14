import os
import json
import re
import smtplib
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
import gspread
from flask import Flask, request, jsonify, Response
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

# -----------------------
# App + Logging
# -----------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -----------------------
# Environment variables
# -----------------------
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").rstrip("/")  # e.g. https://your-service.onrender.com

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

SMTP_SERVER = os.environ.get("SMTP_SERVER", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL", "")
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "ColorCodely")

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")

# The number that plays the daily color code announcement:
COLOR_LINE_NUMBER = os.environ.get("COLOR_LINE_NUMBER", "+12564277808")  # 256-427-7808
TIMEZONE = os.environ.get("TIMEZONE", "America/Chicago")

# Optional: lightweight protection for /daily-call so random people can't trigger calls
CRON_SHARED_SECRET = os.environ.get("CRON_SHARED_SECRET", "")  # if set, require header X-CRON-SECRET to match

# Sheet tab names
SHEET_SUBSCRIBERS = os.environ.get("SHEET_SUBSCRIBERS", "Subscribers")
SHEET_TRANSACTIONS = os.environ.get("SHEET_TRANSACTIONS", "DailyTransactions")

# -----------------------
# Helpers
# -----------------------
def now_local():
    return datetime.now(ZoneInfo(TIMEZONE))

def require_env(name: str, value: str):
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")

def get_base_url():
    # Prefer APP_BASE_URL, otherwise infer from request
    if APP_BASE_URL:
        return APP_BASE_URL
    # request.host_url includes trailing slash
    return request.host_url.rstrip("/")

def sheets_client():
    require_env("GOOGLE_SERVICE_ACCOUNT_JSON", GOOGLE_SERVICE_ACCOUNT_JSON)
    require_env("GOOGLE_SHEET_ID", GOOGLE_SHEET_ID)
    creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    gc = gspread.service_account_from_dict(creds_dict)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    return sh

def get_ws(sheet, title):
    try:
        return sheet.worksheet(title)
    except Exception:
        # If the sheet/tab doesn't exist, fail loudly (better than silently writing nowhere)
        raise RuntimeError(f"Worksheet/tab not found: {title}")

def append_transaction_row(date_str, time_str, call_sid, colors_detected, confidence, transcription):
    sh = sheets_client()
    ws = get_ws(sh, SHEET_TRANSACTIONS)
    ws.append_row([date_str, time_str, call_sid, colors_detected, confidence, transcription])

def fetch_subscribers():
    sh = sheets_client()
    ws = get_ws(sh, SHEET_SUBSCRIBERS)
    rows = ws.get_all_records()  # uses header row
    subscribers = []
    for r in rows:
        email = (r.get("email") or "").strip()
        cell = (r.get("cell_number") or "").strip()
        testing_center = (r.get("testing_center") or "").strip()
        full_name = (r.get("full_name") or "").strip()
        if email or cell:
            subscribers.append({
                "full_name": full_name,
                "email": email,
                "cell_number": cell,
                "testing_center": testing_center
            })
    return subscribers

def smtp_send(to_email: str, subject: str, body: str):
    require_env("SMTP_SERVER", SMTP_SERVER)
    require_env("SMTP_USERNAME", SMTP_USERNAME)
    require_env("SMTP_PASSWORD", SMTP_PASSWORD)
    require_env("SMTP_FROM_EMAIL", SMTP_FROM_EMAIL)

    msg = MIMEMultipart()
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)

def twilio_client():
    require_env("TWILIO_ACCOUNT_SID", TWILIO_ACCOUNT_SID)
    require_env("TWILIO_AUTH_TOKEN", TWILIO_AUTH_TOKEN)
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

def normalize_phone(s: str) -> str:
    # Very light normalization; Twilio wants E.164 (you already store 256... in sheet)
    s = (s or "").strip()
    if not s:
        return ""
    digits = re.sub(r"\D+", "", s)
    if len(digits) == 10:
        return "+1" + digits
    if digits.startswith("1") and len(digits) == 11:
        return "+" + digits
    if s.startswith("+"):
        return s
    return "+" + digits

# A conservative color list (expand any time)
KNOWN_COLORS = [
    "amber","aqua","apple","beige","black","blue","brown","burgundy","charcoal","chartreuse",
    "cherry","chestnut","coral","copper","crimson","cream","eggplant","emerald","fuchsia",
    "ginger","gold","gray","green","hazel","indigo","ivory","jade","khaki","lavender","lemon",
    "lilac","lime","magenta","mahogany","maroon","mauve","mint","navy","olive","onyx","opal",
    "orchid","peach","pearl","periwinkle","pink","platinum","plum","purple","raspberry","red",
    "rose","ruby","sage","sapphire","sienna","silver","tan","teal","turquoise","vanilla",
    "violet","watermelon","yellow"
]

def extract_colors(text: str):
    t = (text or "").lower()
    found = []
    for c in KNOWN_COLORS:
        # match whole-word
        if re.search(rf"\b{re.escape(c)}\b", t):
            found.append(c)
    # keep order of appearance (not list order)
    def first_index(color):
        m = re.search(rf"\b{re.escape(color)}\b", t)
        return m.start() if m else 10**9

    found_sorted = sorted(set(found), key=first_index)
    return found_sorted

def openai_transcribe(audio_bytes: bytes, filename="audio.wav"):
    require_env("OPENAI_API_KEY", OPENAI_API_KEY)

    # Use REST directly (avoids OpenAI python client proxy incompatibility)
    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    files = {"file": (filename, audio_bytes)}
    data = {
        "model": "whisper-1",
        "response_format": "json"
    }

    resp = requests.post(url, headers=headers, files=files, data=data, timeout=90)
    if resp.status_code != 200:
        raise RuntimeError(f"OpenAI transcription failed: {resp.status_code} {resp.text}")
    j = resp.json()
    return (j.get("text") or "").strip()

def build_notification_text(day_upper: str, date_mmddyyyy: str, colors_list):
    # You requested this exact verbiage/format:
    # DAY MM/DD/YYYY
    # TESTING CENTER: City of Huntsville, AL Municipal Court Probation Office
    # The color codes announced at 256-427-7808 are: (colors)
    colors_pretty = ", ".join([c.title() for c in colors_list]) if colors_list else "UNKNOWN"
    lines = [
        f"{day_upper} {date_mmddyyyy}",
        'TESTING CENTER: City of Huntsville, AL Municipal Court Probation Office',
        f"The color codes announced at 256-427-7808 are: {colors_pretty}",
    ]
    return "\n".join(lines)

def send_notifications(subject: str, body: str):
    subscribers = fetch_subscribers()
    sent = {"email": 0, "sms": 0, "errors": []}

    # Email all subscribers that have an email
    for sub in subscribers:
        if sub["email"]:
            try:
                smtp_send(sub["email"], subject, body)
                sent["email"] += 1
            except Exception as e:
                sent["errors"].append({"email": sub["email"], "error": str(e)})

    # OPTIONAL SMS: if you want to enable, set ENABLE_SMS=true in Render env
    enable_sms = os.environ.get("ENABLE_SMS", "false").lower() in ("1", "true", "yes")
    if enable_sms:
        tc = twilio_client()
        for sub in subscribers:
            phone = normalize_phone(sub.get("cell_number"))
            if phone:
                try:
                    tc.messages.create(
                        from_=TWILIO_FROM_NUMBER,
                        to=phone,
                        body=body
                    )
                    sent["sms"] += 1
                except Exception as e:
                    sent["errors"].append({"cell_number": phone, "error": str(e)})

    return sent

# -----------------------
# Routes
# -----------------------
@app.get("/")
def home():
    return "OK", 200

@app.post("/daily-call")
def daily_call():
    # Optional shared-secret protection
    if CRON_SHARED_SECRET:
        incoming = request.headers.get("X-CRON-SECRET", "")
        if incoming != CRON_SHARED_SECRET:
            return jsonify({"error": "unauthorized"}), 401

    require_env("TWILIO_FROM_NUMBER", TWILIO_FROM_NUMBER)

    base = get_base_url()
    twiml_url = f"{base}/twiml/dial_color_line"

    tc = twilio_client()
    call = tc.calls.create(
        to=COLOR_LINE_NUMBER,
        from_=TWILIO_FROM_NUMBER,
        url=twiml_url,
        method="POST"
    )

    logging.info(f"Started call: {call.sid}")
    return jsonify({"call_sid": call.sid, "status": "started"}), 200

@app.post("/twiml/dial_color_line")
def twiml_dial_color_line():
    """
    This TwiML is where the PRIOR BUG happened:
    If we don't explicitly define RecordingStatusCallback, Twilio will NEVER hit /twilio/recording-complete.
    """
    base = get_base_url()
    recording_cb = f"{base}/twilio/recording-complete"

    vr = VoiceResponse()

    # Record what the line plays for up to 90 seconds.
    # No beep, no prompts.
    vr.record(
        max_length=90,
        play_beep=False,
        trim="trim-silence",
        recording_status_callback=recording_cb,
        recording_status_callback_method="POST"
    )

    vr.hangup()
    xml = str(vr)
    return Response(xml, mimetype="text/xml")

@app.post("/twilio/recording-complete")
def twilio_recording_complete():
    """
    Twilio will POST here when recording completes.
    We download the recording audio, transcribe via OpenAI REST,
    extract colors, write to Google Sheets, and email subscribers.
    """
    form = request.form or {}
    recording_url = (form.get("RecordingUrl") or "").strip()  # usually no extension
    recording_sid = (form.get("RecordingSid") or "").strip()
    call_sid = (form.get("CallSid") or "").strip()

    logging.info(f"/twilio/recording-complete hit. CallSid={call_sid} RecordingSid={recording_sid}")

    if not recording_url:
        logging.error("Missing RecordingUrl from Twilio webhook.")
        return ("", 204)

    # Twilio lets you fetch with an extension; wav is typically best for transcription
    audio_fetch_url = recording_url + ".wav"

    try:
        r = requests.get(
            audio_fetch_url,
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            timeout=60
        )
        r.raise_for_status()
        audio_bytes = r.content
    except Exception as e:
        logging.exception("Failed to download Twilio recording audio.")
        # Still write a transaction row so you can see failures in the sheet
        dt = now_local()
        append_transaction_row(
            date_str=dt.strftime("%Y-%m-%d"),
            time_str=dt.strftime("%H:%M:%S"),
            call_sid=call_sid or recording_sid or "",
            colors_detected="",
            confidence=0.0,
            transcription=f"Failed to download recording audio: {e}"
        )
        return ("", 204)

    # Transcribe
    transcription = ""
    colors = []
    confidence = 0.0

    try:
        transcription = openai_transcribe(audio_bytes, filename="recording.wav")
        colors = extract_colors(transcription)
        confidence = 0.9 if len(colors) >= 2 else (0.6 if len(colors) == 1 else 0.2)
    except Exception as e:
        transcription = f"Transcription failed. {e}"
        colors = []
        confidence = 0.0

    # Build message
    dt = now_local()
    day_upper = dt.strftime("%A").upper()
    date_mmddyyyy = dt.strftime("%m/%d/%Y")
    body = build_notification_text(day_upper, date_mmddyyyy, colors)

    # Write to sheet (always)
    try:
        append_transaction_row(
            date_str=dt.strftime("%Y-%m-%d"),
            time_str=dt.strftime("%H:%M:%S"),
            call_sid=call_sid or recording_sid or "",
            colors_detected=", ".join(colors),
            confidence=confidence,
            transcription=transcription
        )
    except Exception:
        logging.exception("Failed writing to Google Sheets (DailyTransactions).")

    # Send email (only if transcription succeeded OR colors found; you can change this rule)
    try:
        subject = f"Color Codes — {day_upper} {date_mmddyyyy}"
        sent = send_notifications(subject, body)
        logging.info(f"Notifications sent: {sent}")
    except Exception:
        logging.exception("Failed sending notifications.")

    return ("", 204)

# -----------------------
# Local dev runner
# -----------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
