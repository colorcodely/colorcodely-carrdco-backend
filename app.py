import os
from datetime import datetime
from threading import Thread
from flask import Flask, request, jsonify, Response
from twilio.rest import Client

from sheets import (
    add_subscriber,
    get_all_subscribers,
    save_daily_transcription,
    get_latest_transcription,
)
from emailer import send_email

app = Flask(__name__)

# -------------------------------------------------
# CONFIG
# -------------------------------------------------
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").rstrip("/")
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM_NUMBER = os.environ["TWILIO_FROM_NUMBER"]

HUNTSVILLE_COLOR_LINE = "+12564277808"

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

PROCESSED_CALL_SIDS = set()

# -------------------------------------------------
# ASYNC HELPER
# -------------------------------------------------
def async_task(fn, *args):
    t = Thread(target=fn, args=args)
    t.daemon = True
    t.start()

# -------------------------------------------------
# CLEAN TRANSCRIPTION
# -------------------------------------------------
def clean_transcription(text):
    if not text:
        return None

    text = " ".join(text.split())

    stop_phrases = [
        "this system is temporarily unable",
        "call again later goodbye",
    ]
    for phrase in stop_phrases:
        idx = text.lower().find(phrase)
        if idx != -1:
            text = text[:idx].strip()

    # De-duplicate repeated sentences
    sentences = [s.strip() for s in text.split(".") if s.strip()]
    seen = set()
    unique = []
    for s in sentences:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            unique.append(s)

    return ". ".join(unique)

# -------------------------------------------------
# TWILIO CALL
# -------------------------------------------------
def start_daily_call():
    call = twilio_client.calls.create(
        to=HUNTSVILLE_COLOR_LINE,
        from_=TWILIO_FROM_NUMBER,
        url=f"{APP_BASE_URL}/twiml/dial_color_line",
        record=True,
        trim="trim-silence",
        recording_status_callback=f"{APP_BASE_URL}/twilio/recording-complete",
        recording_status_callback_event=["completed"],
        timeout=55,
    )
    return call.sid

# -------------------------------------------------
# ROUTES
# -------------------------------------------------
@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/daily-call", methods=["POST"])
def daily_call():
    sid = start_daily_call()
    return jsonify({"status": "started", "call_sid": sid})

@app.route("/twiml/dial_color_line", methods=["POST", "GET"])
def dial_color_line():
    xml = f"""
<Response>
  <Dial
    answerOnBridge="true"
    record="record-from-answer"
    timeLimit="45">
    <Number>{HUNTSVILLE_COLOR_LINE}</Number>
  </Dial>
</Response>
"""
    return Response(xml.strip(), mimetype="text/xml")

@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    call_sid = request.form.get("CallSid")
    raw_text = request.form.get("TranscriptionText", "")

    if call_sid in PROCESSED_CALL_SIDS:
        return ("", 204)

    PROCESSED_CALL_SIDS.add(call_sid)

    cleaned = clean_transcription(raw_text)
    async_task(process_transcription, cleaned)

    return ("", 204)

# -------------------------------------------------
# PROCESS TRANSCRIPTION
# -------------------------------------------------
def process_transcription(text):
    subscribers = get_all_subscribers()

    if not text:
        msg = (
            "The City of Huntsville’s Color Code announcement "
            "could not be confidently confirmed."
        )
        for s in subscribers:
            if s.get("email"):
                send_email(s["email"], "Color Code Update", msg)
        return

    save_daily_transcription(text)

    for s in subscribers:
        if s.get("email"):
            send_email(
                s["email"],
                "Today's Color Code Announcement",
                text,
            )

# -------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
