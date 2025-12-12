import os
from datetime import datetime
from threading import Thread

from flask import Flask, request, jsonify, Response
from twilio.rest import Client
from difflib import get_close_matches

from sheets import (
    add_subscriber,
    get_all_subscribers,
    save_daily_transcription,
    get_latest_transcription,
)
from sms import send_sms
from emailer import send_email
from color_codes import COLOR_CODES

app = Flask(__name__)

# ----------------------------------------
# CONFIG
# ----------------------------------------
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").rstrip("/")

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

HUNTSVILLE_COLOR_LINE = "+12564277808"

LATEST_ANNOUNCEMENT_TEXT = None
NOT_UPDATED_NOTICE_SENT_DATE = None

# Prevent duplicate processing per call
PROCESSED_CALL_SIDS = set()

# ----------------------------------------
# ASYNC
# ----------------------------------------
def async_task(fn, *args, **kwargs):
    t = Thread(target=fn, args=args, kwargs=kwargs)
    t.daemon = True
    t.start()

# ----------------------------------------
# TRANSCRIPTION CLEANUP
# ----------------------------------------
STOP_PHRASES = [
    "if your color is called",
    "you must report",
    "call again later",
    "temporarily unable"
]

def trim_at_stop_phrase(text: str) -> str:
    lower = text.lower()
    for phrase in STOP_PHRASES:
        idx = lower.find(phrase)
        if idx != -1:
            return text[: idx + len(phrase)]
    return text

def normalize_color(word: str):
    word = word.lower().strip()
    matches = get_close_matches(word, COLOR_CODES, n=1, cutoff=0.72)
    return matches[0] if matches else None

def extract_called_colors(transcription: str):
    transcription = trim_at_stop_phrase(transcription)
    words = transcription.replace(",", " ").replace(".", " ").split()

    found = set()
    for word in words:
        color = normalize_color(word)
        if color:
            found.add(color)

    return sorted(found)

def build_clean_announcement(date_str: str, colors: list[str]) -> str:
    if not colors:
        return (
            f"The City of Huntsville’s Color Code announcement for {date_str} "
            "could not be confidently confirmed."
        )

    formatted = ", ".join(c.title() for c in colors)

    return (
        f"The City of Huntsville’s Color Code Colors for {date_str} are:\n\n"
        f"{formatted}.\n\n"
        "If your color is called, you must report for drug screening."
    )

# ----------------------------------------
# HEALTH
# ----------------------------------------
@app.route("/health")
def health():
    return jsonify({"status": "ok"})

# ----------------------------------------
# TWILIO CALL
# ----------------------------------------
def start_color_line_call():
    twiml_url = f"{APP_BASE_URL}/twiml/dial_color_line"
    callback_url = f"{APP_BASE_URL}/twilio/recording-complete"

    call = twilio_client.calls.create(
        to=HUNTSVILLE_COLOR_LINE,
        from_=TWILIO_FROM_NUMBER,
        url=twiml_url,
        record=True,
        recording_status_callback=callback_url,
        recording_status_callback_event=["completed"],
    )
    return call.sid

# ----------------------------------------
# TWIML
# ----------------------------------------
@app.route("/twiml/dial_color_line", methods=["GET", "POST"])
def twiml_dial_color_line():
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial record="record-from-answer-dual" timeLimit="65">
    <Number>{HUNTSVILLE_COLOR_LINE}</Number>
  </Dial>
</Response>
"""
    return Response(xml, mimetype="text/xml")

# ----------------------------------------
# DAILY CALL (Render Cron)
# ----------------------------------------
@app.route("/daily-call", methods=["POST"])
def daily_call():
    call_sid = start_color_line_call()
    return jsonify({"status": "started", "call_sid": call_sid})

# ----------------------------------------
# TRANSCRIPTION HANDLER
# ----------------------------------------
def _process_transcription(call_sid: str, transcription_text: str):
    global LATEST_ANNOUNCEMENT_TEXT, NOT_UPDATED_NOTICE_SENT_DATE

    if call_sid in PROCESSED_CALL_SIDS:
        return

    PROCESSED_CALL_SIDS.add(call_sid)

    cleaned_colors = extract_called_colors(transcription_text)
    today = datetime.now().strftime("%A, %B %d")
    announcement = build_clean_announcement(today, cleaned_colors)

    LATEST_ANNOUNCEMENT_TEXT = announcement
    NOT_UPDATED_NOTICE_SENT_DATE = None

    save_daily_transcription(announcement)

    subscribers = get_all_subscribers()

    for sub in subscribers:
        phone = sub.get("cell_number")
        email = sub.get("email")
        name = sub.get("full_name") or "there"

        if phone:
            async_task(send_sms, phone, announcement)

        if email:
            body = f"Hello {name},\n\n{announcement}\n\n— ColorCodely"
            async_task(send_email, email, "Today's ColorCodely announcement", body)

# ----------------------------------------
# TWILIO CALLBACK
# ----------------------------------------
@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    form = request.form
    call_sid = form.get("CallSid")

    transcription_text = form.get("TranscriptionText") or ""

    async_task(_process_transcription, call_sid, transcription_text)
    return ("", 204)

# ----------------------------------------
# LOCAL
# ----------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
