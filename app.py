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

# Last known good announcement text
LATEST_ANNOUNCEMENT_TEXT = None

# Tracks whether we've already sent a "not updated yet" notice today
NOT_UPDATED_NOTICE_SENT_DATE = None


# ----------------------------------------
# ASYNC HELPER
# ----------------------------------------
def async_task(fn, *args, **kwargs):
    """Run in background thread to avoid Render timeouts."""
    t = Thread(target=fn, args=args, kwargs=kwargs)
    t.daemon = True
    t.start()


# ----------------------------------------
# HELPERS
# ----------------------------------------
def get_form_field(data, *keys):
    for key in keys:
        if key in data and isinstance(data[key], str) and data[key].strip():
            return data[key].strip()
    return ""


def clean_transcription_text(raw_text: str) -> str:
    if not raw_text:
        return raw_text

    normalized = " ".join(raw_text.split())
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
    global LATEST_ANNOUNCEMENT_TEXT

    form = request.form

    full_name = get_form_field(form, "full_name", "name", "Name")
    email = get_form_field(form, "email", "Email")
    phone = get_form_field(form, "phone", "cell", "cell_number", "Cell Number")
    testing_center = get_form_field(form, "testing_center", "Testing Center")

    if not email or not phone or not testing_center:
        return jsonify({
            "status": "error",
            "message": "Missing required fields (email, phone, testing_center).",
        }), 400

    try:
        add_subscriber(full_name, email, phone, testing_center)
    except Exception as e:
        app.logger.exception("Failed to add subscriber: %s", e)

    if LATEST_ANNOUNCEMENT_TEXT is None:
        try:
            start_color_line_call()
        except Exception as e:
            app.logger.exception("Initial call error: %s", e)

        sms_body = (
            "Welcome to ColorCodely alerts!\n\n"
            "You’re subscribed. We’ve started a call to fetch the latest "
            "color code announcement and you’ll receive it shortly."
        )
        email_subject = "Welcome to ColorCodely alerts"
        email_body = (
            f"Hi {full_name or ''},\n\n"
            "Thanks for subscribing to ColorCodely.\n"
            "We’re fetching the latest announcement now.\n\n"
            "— ColorCodely"
        )
    else:
        sms_body = (
            "Welcome to ColorCodely alerts!\n\n"
            "Here is the most recent color code announcement:\n\n"
            f"{LATEST_ANNOUNCEMENT_TEXT}"
        )
        email_subject = "Welcome to ColorCodely"
        email_body = (
            f"Hi {full_name or ''},\n\n"
            "You're now subscribed.\n\n"
            f"Latest announcement:\n\n{LATEST_ANNOUNCEMENT_TEXT}\n\n"
            "— ColorCodely"
        )

    async_task(send_sms, phone, sms_body)
    async_task(send_email, email, email_subject, email_body)

    return jsonify({"status": "ok"})


# ----------------------------------------
# TWIML FOR OUTBOUND CALL (UPDATED)
# ----------------------------------------
@app.route("/twiml/dial_color_line", methods=["POST", "GET"])
def twiml_dial_color_line():

    recording_callback = f"{APP_BASE_URL}/twilio/recording-complete"

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial
      record="record-from-answer-dual"
      timeLimit="60"
      recordingStatusCallback="{recording_callback}"
      recordingStatusCallbackEvent="completed">
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
    try:
        call_sid = start_color_line_call()
        return jsonify({"status": "started", "call_sid": call_sid})
    except Exception as e:
        app.logger.exception("Daily call error: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ----------------------------------------
# BACKGROUND TRANSCRIPTION
# ----------------------------------------
def _process_transcription(transcription_text: str):
    global LATEST_ANNOUNCEMENT_TEXT, NOT_UPDATED_NOTICE_SENT_DATE

    try:
        last_date, last_text = get_latest_transcription()
    except Exception:
        last_date, last_text = None, None

    is_same = last_text and transcription_text.strip() == last_text.strip()

    try:
        subscribers = get_all_subscribers()
    except Exception:
        subscribers = []

    if is_same:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if NOT_UPDATED_NOTICE_SENT_DATE == today:
            return

        NOT_UPDATED_NOTICE_SENT_DATE = today

        info_sms = (
            "ColorCodely update:\n\n"
            "Today's color code recording has not been updated yet. "
            "You'll be notified when a new announcement is available."
        )
        info_subject = "ColorCodely: No new update yet"

        for sub in subscribers:
            phone = sub.get("cell_number")
            email = sub.get("email")
            name = sub.get("full_name") or "there"

            if phone:
                async_task(send_sms, phone, info_sms)
            if email:
                async_task(send_email, email, info_subject,
                           f"Hello {name},\n\n{info_sms}\n\n— ColorCodely")
        return

    # NEW UPDATE
    LATEST_ANNOUNCEMENT_TEXT = transcription_text
    NOT_UPDATED_NOTICE_SENT_DATE = None

    try:
        save_daily_transcription(transcription_text)
    except Exception:
        pass

    sms_body = f"Today's color code announcement:\n\n{transcription_text}"
    email_subject = "Today's ColorCodely announcement"

    for sub in subscribers:
        phone = sub.get("cell_number")
        email = sub.get("email")
        name = sub.get("full_name") or "there"

        if phone:
            async_task(send_sms, phone, sms_body)
        if email:
            email_body = (
                f"Hello {name},\n\n"
                f"{sms_body}\n\n— ColorCodely"
            )
            async_task(send_email, email, email_subject, email_body)


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
