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
from sms import send_sms
from emailer import send_email

app = Flask(__name__)

# ----------------------------------------
# ENV / CONFIG
# ----------------------------------------
SPREADSHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").rstrip("/")

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# City of Huntsville, AL Municipal Court Probation Office color code line
HUNTSVILLE_COLOR_LINE = "+12564277808"

# Last known good announcement text (for welcome messages, etc.)
LATEST_ANNOUNCEMENT_TEXT = None

# Tracks whether we've already sent a "not updated yet" notice today
NOT_UPDATED_NOTICE_SENT_DATE = None


# ----------------------------------------
# ASYNC HELPER
# ----------------------------------------
def async_task(fn, *args, **kwargs):
    """
    Runs any function in a background thread so the API
    can return immediately (prevents Render 502 timeouts).
    """
    t = Thread(target=fn, args=args, kwargs=kwargs)
    t.daemon = True
    t.start()


# ----------------------------------------
# HELPERS
# ----------------------------------------
def get_form_field(data, *keys):
    """Helper to read Carrd form fields, trying multiple possible names."""
    for key in keys:
        if key in data and isinstance(data[key], str) and data[key].strip():
            return data[key].strip()
    return ""


def clean_transcription_text(raw_text: str) -> str:
    """
    Cleans up Twilio transcriptions if the IVR recording loops.
    Removes duplicated sentences while preserving order.
    """
    if not raw_text:
        return raw_text

    # Collapse whitespace
    normalized = " ".join(raw_text.split())
    # Split on periods and strip
    parts = [p.strip() for p in normalized.split(".") if p.strip()]

    if not parts:
        return normalized

    seen = set()
    unique_parts = []

    for p in parts:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            unique_parts.append(p)

    cleaned = ". ".join(unique_parts)

    # Preserve trailing period if original had one
    if normalized.strip().endswith("."):
        cleaned += "."

    return cleaned


# ----------------------------------------
# HEALTH CHECK
# ----------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ----------------------------------------
# TWILIO CALL OUTBOUND
# ----------------------------------------
def start_color_line_call():
    """Triggers Twilio to call the Huntsville color line."""
    if not APP_BASE_URL:
        raise RuntimeError("APP_BASE_URL is not set")

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
# CARRD FORM SUBMIT
# ----------------------------------------
@app.route("/submit", methods=["POST"])
def submit():
    """
    Receives Carrd form submission.
    Saves subscriber to Google Sheets.
    Sends welcome SMS + email asynchronously.
    """
    global LATEST_ANNOUNCEMENT_TEXT

    form = request.form

    full_name = get_form_field(form, "full_name", "name", "Name")
    email = get_form_field(form, "email", "Email")
    phone = get_form_field(form, "phone", "cell", "cell_number", "Cell Number")
    testing_center = get_form_field(form, "testing_center", "Testing Center")

    if not email or not phone or not testing_center:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Missing required fields (email, phone, testing_center).",
                }
            ),
            400,
        )

    # 1) Save to Google Sheets
    try:
        add_subscriber(full_name, email, phone, testing_center)
    except Exception as e:
        app.logger.exception("Failed to add subscriber: %s", e)

    # 2) Build welcome messages
    if LATEST_ANNOUNCEMENT_TEXT is None:
        # Trigger first-ever call
        try:
            start_color_line_call()
        except Exception as e:
            app.logger.exception("Failed to trigger initial call in submit: %s", e)

        sms_body = (
            "Welcome to ColorCodely alerts!\n\n"
            "You’re subscribed. We’ve started a call to fetch the latest "
            "color code announcement and you’ll receive it as soon as it’s available."
        )
        email_subject = "Welcome to ColorCodely alerts"
        email_body = (
            f"Hi {full_name or ''},\n\n"
            "Thanks for subscribing to ColorCodely.\n\n"
            "We’re fetching the latest color code announcement now. "
            "You’ll start receiving daily announcements as soon as the first "
            "recording is processed.\n\n"
            "— ColorCodely"
        )
    else:
        sms_body = (
            "Welcome to ColorCodely alerts!\n\n"
            "Here is the most recent color code announcement:\n\n"
            f"{LATEST_ANNOUNCEMENT_TEXT}"
        )
        email_subject = "Welcome to ColorCodely – Latest Announcement"
        email_body = (
            f"Hi {full_name or ''},\n\n"
            "You're now subscribed to ColorCodely daily alerts.\n\n"
            "Here is the most recent color code announcement:\n\n"
            f"{LATEST_ANNOUNCEMENT_TEXT}\n\n"
            "— ColorCodely"
        )

    # 3) Send welcome messages asynchronously (avoid timeouts)
    async_task(send_sms, phone, sms_body)
    async_task(send_email, email, email_subject, email_body)

    return jsonify({"status": "ok"})


# ----------------------------------------
# TWIML FOR TWILIO OUTBOUND CALL
# ----------------------------------------
@app.route("/twiml/dial_color_line", methods=["POST", "GET"])
def twiml_dial_color_line():
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial record="record-from-answer-dual" timeLimit="60">
    <Number>{HUNTSVILLE_COLOR_LINE}</Number>
  </Dial>
</Response>
"""
    return Response(xml, mimetype="text/xml")


# ----------------------------------------
# DAILY CALL ENDPOINT (for Render Cron)
# ----------------------------------------
@app.route("/daily-call", methods=["POST"])
def daily_call():
    try:
        call_sid = start_color_line_call()
        return jsonify({"status": "started", "call_sid": call_sid})
    except Exception as e:
        app.logger.exception("Error starting daily call: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ----------------------------------------
# BACKGROUND TRANSCRIPTION PROCESSOR
# ----------------------------------------
def _process_transcription(transcription_text: str):
    global LATEST_ANNOUNCEMENT_TEXT, NOT_UPDATED_NOTICE_SENT_DATE

    # 1) Compare with latest stored
    try:
        last_date, last_text = get_latest_transcription()
    except Exception as e:
        app.logger.exception("Failed to read latest transcription: %s", e)
        last_date, last_text = None, None

    is_same_as_last = last_text and transcription_text.strip() == last_text.strip()

    # 2) Load all subscribers
    try:
        subscribers = get_all_subscribers()
    except Exception as e:
        app.logger.exception("Failed to load subscribers: %s", e)
        subscribers = []

    # 3) Handle "not updated yet"
    if is_same_as_last:
        today_str = datetime.utcnow().strftime("%Y-%m-%d")

        # Only send this notice once per day
        if NOT_UPDATED_NOTICE_SENT_DATE == today_str:
            return

        NOT_UPDATED_NOTICE_SENT_DATE = today_str

        info_sms = (
            "ColorCodely update:\n\n"
            "The Huntsville Municipal Court color-code recording has not "
            "been updated yet today. We’ll notify you as soon as a new "
            "announcement is available."
        )
        info_subject = "ColorCodely: recording not updated yet"
        info_body_template = (
            "Hello {name},\n\n"
            "Today's color code announcement hasn't been updated yet. "
            "We'll notify you as soon as a new announcement becomes available.\n\n"
            "— ColorCodely"
        )

        for sub in subscribers:
            phone = sub.get("cell_number")
            email = sub.get("email")
            name = sub.get("full_name") or "there"

            if phone:
                async_task(send_sms, phone, info_sms)

            if email:
                body = info_body_template.format(name=name)
                async_task(send_email, email, info_subject, body)

        return

    # 4) NEW transcription
    LATEST_ANNOUNCEMENT_TEXT = transcription_text
    NOT_UPDATED_NOTICE_SENT_DATE = None

    # Save to Sheets
    try:
        save_daily_transcription(transcription_text)
    except Exception as e:
        app.logger.exception("Failed to save daily transcription: %s", e)

    # Notify subscribers
    sms_body = f"Today's color code announcement:\n\n{transcription_text}"
    email_subject = "Today's ColorCodely announcement"
    email_body_template = (
        "Hello {name},\n\n"
        "Here is today's color code announcement:\n\n"
        "{text}\n\n"
        "— ColorCodely"
    )

    for sub in subscribers:
        phone = sub.get("cell_number")
        email = sub.get("email")
        name = sub.get("full_name") or "there"

        if phone:
            async_task(send_sms, phone, sms_body)

        if email:
            body = email_body_template.format(name=name, text=transcription_text)
            async_task(send_email, email, email_subject, body)


# ----------------------------------------
# TWILIO CALLBACK FOR RECORDING
# ----------------------------------------
@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    form = request.form

    transcription_text = form.get("TranscriptionText")
    if not transcription_text:
        transcription_text = (
            "No transcription text was provided by Twilio. "
            "You may need to enable transcription."
        )
    else:
        transcription_text = clean_transcription_text(transcription_text)

    # Process in background and return immediately
    async_task(_process_transcription, transcription_text)

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
