import os
import re
import time
import tempfile
from datetime import datetime
from threading import Thread
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request, jsonify, Response
from twilio.rest import Client

from sheets import (
    add_subscriber,
    get_all_subscribers,
    save_daily_transcription,
    get_latest_transcription,
)
from sms import send_sms
from emailer import send_email

app = Flask(__name__)

# ----------------------------------------
# ENV / CONFIG
# ----------------------------------------
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").rstrip("/")

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")

# OpenAI Whisper via REST (no openai python package required)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# City of Huntsville, AL Municipal Court Probation Office color code line
HUNTSVILLE_COLOR_LINE = "+12564277808"

CST = ZoneInfo("America/Chicago")

# Optional: if you want failures to go to you only (recommended)
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "colorcodely@gmail.com")

# Tracks "sent today" guard (in-memory; also backed by Sheets check)
LAST_SUCCESSFUL_SEND_DATE_CST = None


# ----------------------------------------
# COLOR LIST (authoritative)
# ----------------------------------------
VALID_COLORS = [
    "amber", "apple", "aqua", "banana", "beige", "black", "blue", "bone", "bronze", "brown",
    "burgundy", "charcoal", "chartreuse", "cherry", "chestnut", "copper", "coral", "cream", "creme",
    "crimson", "eggplant", "emerald", "fuchsia", "ginger", "gold", "gray", "green", "hazel", "indigo",
    "ivory", "jade", "jasmine", "khaki", "lavender", "lemon", "lilac", "lime", "magenta", "mahogany",
    "maroon", "mauve", "mint", "navy", "olive", "onyx", "opal", "orange", "orchid", "peach", "pearl",
    "periwinkle", "pink", "platinum", "plum", "purple", "raspberry", "red", "rose", "ruby", "sage",
    "sapphire", "sienna", "silver", "tan", "tangerine", "teal", "turquoise", "vanilla", "violet",
    "watermelon", "white", "yellow",
]
VALID_COLOR_SET = set(VALID_COLORS)


# ----------------------------------------
# ASYNC HELPER
# ----------------------------------------
def async_task(fn, *args, **kwargs):
    t = Thread(target=fn, args=args, kwargs=kwargs)
    t.daemon = True
    t.start()


# ----------------------------------------
# SMALL HELPERS
# ----------------------------------------
def now_cst():
    return datetime.now(tz=CST)

def today_cst_str():
    return now_cst().strftime("%Y-%m-%d")

def day_and_date_line():
    # SATURDAY 12/13/2025
    dt = now_cst()
    return f"{dt.strftime('%A').upper()} {dt.strftime('%m/%d/%Y')}"

def is_valid_email(email: str) -> bool:
    if not email:
        return False
    e = email.strip().lower()
    if e == "email":
        return False
    return ("@" in e) and ("." in e)

def is_valid_phone(phone: str) -> bool:
    # Minimal check (Twilio will enforce E.164). We just avoid obviously bad values.
    if not phone:
        return False
    p = phone.strip()
    return p.startswith("+") and len(p) >= 10

def get_form_field(data, *keys):
    for key in keys:
        if key in data and isinstance(data[key], str) and data[key].strip():
            return data[key].strip()
    return ""


# ----------------------------------------
# TEXT CLEANUP + COLOR EXTRACTION
# ----------------------------------------
def normalize_common_mishears(text: str) -> str:
    """
    Fixes common transcription mishears we have seen:
    - "lilac mall" -> lilac mauve
    - "rolls" -> rose
    - "a plant"/"8 plant" -> eggplant
    """
    if not text:
        return text

    t = " ".join(text.split())
    t_low = t.lower()

    # targeted replacements (keep them gentle)
    t_low = re.sub(r"\blilac mall\b", "lilac mauve", t_low)
    t_low = re.sub(r"\brolls\b", "rose", t_low)
    t_low = re.sub(r"\ba plant\b", "eggplant", t_low)
    t_low = re.sub(r"\b8 plant\b", "eggplant", t_low)
    t_low = re.sub(r"\begg plant\b", "eggplant", t_low)
    t_low = re.sub(r"\bcreme\b", "cream", t_low)

    return t_low


def extract_colors(transcribed_text: str):
    """
    Returns a list like ["CHESTNUT","MINT","PEARL"] in the order first encountered,
    de-duped.
    """
    if not transcribed_text:
        return []

    t = normalize_common_mishears(transcribed_text)

    found = []
    seen = set()

    # scan word-by-word using regex boundaries for each known color
    # (fast enough given small color list)
    for color in VALID_COLORS:
        # We'll find all occurrences and record their first position, then sort by position.
        pass

    positions = []
    for color in VALID_COLORS:
        m = re.search(rf"\b{re.escape(color)}\b", t)
        if m:
            positions.append((m.start(), color))

    positions.sort(key=lambda x: x[0])

    for _, color in positions:
        if color not in seen:
            seen.add(color)
            found.append(color.upper())

    return found


def build_announcement_message(colors_list):
    """
    Produces the approved output format.
    """
    header = day_and_date_line()
    testing_center = "City of Huntsville, AL Municipal Court Probation Office"
    codes = ", ".join(colors_list) if colors_list else "NO CODES CONFIRMED"

    subject = f"Color Code Announcement — {header}"
    body = (
        f"{header}\n\n"
        "TESTING CENTER:\n"
        f"{testing_center}\n\n"
        "The color codes announced at 256-427-7808 are:\n"
        f"{codes}"
    )
    sms = (
        f"{header}\n\n"
        f"TESTING CENTER:\n{testing_center}\n\n"
        "The color codes announced at 256-427-7808 are:\n"
        f"{codes}"
    )
    return subject, body, sms


# ----------------------------------------
# HEALTH CHECK
# ----------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ----------------------------------------
# TWILIO CALL OUTBOUND (started by cron)
# ----------------------------------------
def start_color_line_call():
    if not APP_BASE_URL:
        raise RuntimeError("APP_BASE_URL is not set")

    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_FROM_NUMBER:
        raise RuntimeError("Twilio env vars missing: TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER")

    twiml_url = f"{APP_BASE_URL}/twiml/dial_color_line"
    callback_url = f"{APP_BASE_URL}/twilio/recording-complete"

    call = twilio_client.calls.create(
        to=HUNTSVILLE_COLOR_LINE,
        from_=TWILIO_FROM_NUMBER,
        url=twiml_url,
        method="POST",
        record=True,
        recording_status_callback=callback_url,
        recording_status_callback_method="POST",
        recording_status_callback_event=["completed"],
    )
    return call.sid


# ----------------------------------------
# CARRD FORM SUBMIT
# ----------------------------------------
@app.route("/submit", methods=["POST"])
def submit():
    """
    Receives Carrd form submission.
    Saves subscriber to Google Sheets.
    Sends a welcome email/SMS using the latest stored announcement (if available),
    WITHOUT triggering an extra Twilio call (avoids duplicate calls).
    """
    form = request.form

    full_name = get_form_field(form, "full_name", "name", "Name")
    email = get_form_field(form, "email", "Email")
    phone = get_form_field(form, "phone", "cell", "cell_number", "Cell Number")
    testing_center = get_form_field(form, "testing_center", "Testing Center")

    if not email or not phone or not testing_center:
        return jsonify({"status": "error", "message": "Missing required fields (email, phone, testing_center)."}), 400

    # Save subscriber
    try:
        add_subscriber(full_name, email, phone, testing_center)
    except Exception as e:
        app.logger.exception("Failed to add subscriber: %s", e)

    # Pull most recent announcement (if any)
    last_date, last_text = (None, None)
    try:
        last_date, last_text = get_latest_transcription()
    except Exception as e:
        app.logger.exception("Failed to read latest transcription in submit: %s", e)

    if last_text:
        # Try to re-extract colors to format cleanly
        colors = extract_colors(last_text)
        subject, email_body, sms_body = build_announcement_message(colors)
        welcome_subject = f"Welcome to ColorCodely — Latest Announcement"
        welcome_email = f"Hello {full_name or 'there'},\n\nYou're subscribed.\n\n{email_body}\n"
        welcome_sms = f"Welcome to ColorCodely!\n\n{sms_body}"
    else:
        welcome_subject = "Welcome to ColorCodely"
        welcome_email = (
            f"Hello {full_name or 'there'},\n\n"
            "You're subscribed to ColorCodely alerts.\n\n"
            "Next scheduled announcement will be sent after the daily call runs at 6:04 AM CST.\n"
        )
        welcome_sms = (
            "Welcome to ColorCodely!\n\n"
            "You're subscribed. Next scheduled announcement will be sent after the daily call runs at 6:04 AM CST."
        )

    # Send asynchronously
    if is_valid_phone(phone):
        async_task(send_sms, phone, welcome_sms)

    if is_valid_email(email):
        async_task(send_email, email, welcome_subject, welcome_email)

    return jsonify({"status": "ok"})


# ----------------------------------------
# TWIML FOR TWILIO OUTBOUND CALL
# ----------------------------------------
@app.route("/twiml/dial_color_line", methods=["POST", "GET"])
def twiml_dial_color_line():
    """
    We record the call leg after answer to minimize ring artifacts.
    """
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial record="record-from-answer" timeLimit="65" trim="trim-silence">
    <Number>{HUNTSVILLE_COLOR_LINE}</Number>
  </Dial>
</Response>
"""
    return Response(xml, mimetype="text/xml")


# ----------------------------------------
# DAILY CALL ENDPOINT (for Render Cron + manual tests)
# ----------------------------------------
@app.route("/daily-call", methods=["POST", "GET"])
def daily_call():
    """
    Triggers Twilio to call the color line.
    GET is allowed so you can trigger in browser if needed.
    """
    try:
        call_sid = start_color_line_call()
        return jsonify({"status": "started", "call_sid": call_sid})
    except Exception as e:
        app.logger.exception("Error starting daily call: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ----------------------------------------
# OPENAI WHISPER TRANSCRIPTION (REST)
# ----------------------------------------
def download_twilio_recording(recording_url: str, out_path: str) -> None:
    """
    Twilio sends RecordingUrl without extension sometimes.
    We'll append .mp3 for convenience.
    """
    if not recording_url:
        raise RuntimeError("No RecordingUrl provided by Twilio callback")

    url = recording_url
    if not url.endswith(".mp3"):
        url = url + ".mp3"

    r = requests.get(url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), timeout=60)
    r.raise_for_status()

    with open(out_path, "wb") as f:
        f.write(r.content)


def whisper_transcribe(audio_path: str) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set in Render environment")

    # OpenAI transcription endpoint
    endpoint = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    with open(audio_path, "rb") as f:
        files = {"file": (os.path.basename(audio_path), f, "audio/mpeg")}
        data = {
            "model": "whisper-1",
            # helpful for your use-case
            "temperature": "0",
            # hint words
            "prompt": "City of Huntsville Color Code Colors. Colors include: " + ", ".join([c.upper() for c in VALID_COLORS]),
        }
        resp = requests.post(endpoint, headers=headers, files=files, data=data, timeout=120)

    # Handle quota / billing errors cleanly
    if resp.status_code >= 400:
        try:
            return f"__OPENAI_ERROR__ {resp.text}"
        except Exception:
            return "__OPENAI_ERROR__ (unreadable response)"

    j = resp.json()
    return (j.get("text") or "").strip()


# ----------------------------------------
# MAIN PIPELINE: RECORDING -> WHISPER -> COLORS -> SEND
# ----------------------------------------
def should_send_today_guard():
    """
    Prevent multiple full sends in a single CST day (cron may be run multiple times).
    We also check Sheets last transcription date as a fallback.
    """
    global LAST_SUCCESSFUL_SEND_DATE_CST
    today = today_cst_str()

    if LAST_SUCCESSFUL_SEND_DATE_CST == today:
        return False

    # If Sheets has a transcription already stored for today, don't send again
    try:
        last_date, _ = get_latest_transcription()
        if last_date and str(last_date).startswith(today):
            LAST_SUCCESSFUL_SEND_DATE_CST = today
            return False
    except Exception:
        pass

    return True


def send_to_all_subscribers(subject: str, email_body: str, sms_body: str):
    try:
        subscribers = get_all_subscribers()
    except Exception as e:
        app.logger.exception("Failed to load subscribers: %s", e)
        subscribers = []

    for sub in subscribers:
        phone = (sub.get("cell_number") or "").strip()
        email = (sub.get("email") or "").strip()

        if is_valid_phone(phone):
            async_task(send_sms, phone, sms_body)

        if is_valid_email(email):
            async_task(send_email, email, subject, f"Hello {sub.get('full_name') or 'there'},\n\n{email_body}\n")


def notify_admin_failure(msg: str):
    """
    Avoid blasting all subscribers with failure notices.
    """
    try:
        subj = "ColorCodely: Transcription failed"
        body = f"Transcription failed.\n\n{msg}\n"
        if ADMIN_EMAIL and is_valid_email(ADMIN_EMAIL):
            async_task(send_email, ADMIN_EMAIL, subj, body)
    except Exception:
        pass


def process_recording_with_whisper(recording_url: str):
    """
    Downloads the Twilio recording audio -> Whisper -> extract colors -> save -> send.
    """
    global LAST_SUCCESSFUL_SEND_DATE_CST

    if not should_send_today_guard():
        app.logger.info("Guard active: already sent today. Skipping send.")
        return

    tmp_dir = tempfile.mkdtemp(prefix="colorcodely_")
    audio_path = os.path.join(tmp_dir, "recording.mp3")

    try:
        download_twilio_recording(recording_url, audio_path)
    except Exception as e:
        app.logger.exception("Failed to download recording: %s", e)
        notify_admin_failure(f"Failed to download Twilio recording.\nError: {e}")
        return

    try:
        text = whisper_transcribe(audio_path)
    except Exception as e:
        app.logger.exception("Whisper exception: %s", e)
        notify_admin_failure(f"Whisper exception.\nError: {e}")
        return

    # If OpenAI returned an error payload, email admin only
    if text.startswith("__OPENAI_ERROR__"):
        notify_admin_failure(f"OpenAI response:\n{text.replace('__OPENAI_ERROR__', '').strip()}")
        return

    colors = extract_colors(text)

    # If we got nothing usable, notify admin only
    if not colors:
        notify_admin_failure(
            "The transcription completed but no valid colors were confidently detected.\n\n"
            f"Raw transcription:\n{text}"
        )
        return

    # Save in Sheets (store raw transcription, not just colors)
    try:
        save_daily_transcription(text)
    except Exception as e:
        app.logger.exception("Failed to save daily transcription: %s", e)

    subject, email_body, sms_body = build_announcement_message(colors)

    # Send to all subscribers
    send_to_all_subscribers(subject, email_body, sms_body)

    # Mark sent today
    LAST_SUCCESSFUL_SEND_DATE_CST = today_cst_str()


# ----------------------------------------
# TWILIO CALLBACK FOR RECORDING COMPLETED
# ----------------------------------------
@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    """
    Twilio posts here after the call recording is completed.
    We use RecordingUrl to download audio and transcribe with Whisper.
    """
    form = request.form
    recording_url = form.get("RecordingUrl")  # key for recordings callback
    call_sid = form.get("CallSid", "")

    if not recording_url:
        # Some Twilio callbacks may provide RecordingSid only
        # but RecordingUrl is typical; if absent, notify admin and exit.
        notify_admin_failure(f"No RecordingUrl received from Twilio callback. CallSid={call_sid}")
        return ("", 204)

    # Run in background so we respond quickly (prevents timeouts)
    async_task(process_recording_with_whisper, recording_url)

    return ("", 204)


# ----------------------------------------
# LOCAL DEV ENTRY
# ----------------------------------------
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True,
    )
