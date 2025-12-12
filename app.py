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

# The Huntsville, AL Municipal Court Probation color-code line
HUNTSVILLE_COLOR_LINE = "+12564277808"

# Last known good announcement text
LATEST_ANNOUNCEMENT_TEXT = None

# Tracks whether we've already sent a "not updated yet" notice today
NOT_UPDATED_NOTICE_SENT_DATE = None


# ----------------------------------------
# ASYNC HELPER
# ----------------------------------------
def async_task(fn, *args, **kwargs):
    """Run functions async so Render doesn't timeout."""
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
    """Remove duplicated sentences from looping IVR recordings."""
    if not raw_text:
        return raw_text

    normalized = " ".join(raw_text.split())
    parts = [p.strip() for p in normalized.split(".") if p.strip()]

    seen = set()
    unique_parts = []

    for p in parts:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            unique_parts.append(p)

    cleaned = ". ".join(unique_parts)
    if normalized.endswith("."):
        cleaned += "."
    return cleaned


# ----------------------------------------
# HEALTH CHECK
# ----------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ----------------------------------------
# TWILIO OUTBOUND CALL — Option A
# ----------------------------------------
def start_color_line_call():
    """Outbound call that triggers our custom TwiML recording step."""
    if not APP_BASE_URL:
        raise RuntimeError("APP_BASE_URL is not set")

    # Step 1: Twilio hits this TwiML
    twiml_url = f"{APP_BASE_URL}/twiml/start_recording"

    # Step 2: Twilio posts the recording + transcription here
    callback_url = f"{APP_BASE_URL}/twilio/recording-complete"

    call = twilio_client.calls.create(
        to=HUNTSVILLE_COLOR_LINE,
        from_=TWILIO_FROM_NUMBER,
        url=twiml_url,
        record=False,  # We control recording manually using <Record>
        recording_status_callback=callback_url,
        recording_status_callback_event=["completed"],
    )
    return call.sid


# ----------------------------------------
# TWIML STEP 1 — START RECORDING PROPERLY
# ----------------------------------------
@app.route("/twiml/start_recording", methods=["POST", "GET"])
def twiml_start_recording():
    """
    Option A:
    Twilio calls *your backend*, then your backend tells Twilio to RECORD the testing center.
    """

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Record
        beep="true"
        playBeep="true"
        timeout="8"
        transcribe="true"
        transcriptionType="auto"
        transcribeCallback="{APP_BASE_URL}/twilio/recording-complete"
        maxLength="75"
        trim="trim-silence"
    />
</Response>"""

    return Response(xml, mimetype="text/xml")


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
            "message": "Missing required fields (email, phone, testing_center)."
        }), 400

    try:
        add_subscriber(full_name, email, phone, testing_center)
    except Exception as e:
        app.logger.exception("Failed to add subscriber: %s", e)

    # Build welcome messages
    if LATEST_ANNOUNCEMENT_TEXT is None:
        # first subscriber triggers first outbound call
        try:
            start_color_line_call()
        except Exception as e:
            app.logger.exception("Failed to trigger initial call: %s", e)

        sms_body = (
            "Welcome to ColorCodely alerts!\n\n"
            "We're fetching today's color code announcement now."
        )
        email_subject = "Welcome to ColorCodely"
        email_body = (
            f"Hi {full_name or ''},\n\n"
            "You're subscribed! The first announcement will be sent shortly.\n\n"
            "— ColorCodely"
        )
    else:
        sms_body = (
            "Welcome to ColorCodely alerts!\n\n"
            f"Most recent announcement:\n\n{LATEST_ANNOUNCEMENT_TEXT}"
        )
        email_subject = "Welcome to ColorCodely"
        email_body = (
            f"Hi {full_name or ''},\n\n"
            f"Most recent announcement:\n{LATEST_ANNOUNCEMENT_TEXT}\n\n"
            "— ColorCodely"
        )

    async_task(send_sms, phone, sms_body)
    async_task(send_email, email, email_subject, email_body)

    return jsonify({"status": "ok"})


# ----------------------------------------
# RENDER CRON — DAILY CALL START
# ----------------------------------------
@app.route("/daily-call", methods=["POST"])
def daily_call():
    try:
        sid = start_color_line_call()
        return jsonify({"status": "started", "call_sid": sid})
    except Exception as e:
        app.logger.exception("Error starting daily call: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ----------------------------------------
# PROCESSING COMPLETED TRANSCRIPTION
# ----------------------------------------
def _process_transcription(text: str):
    global LATEST_ANNOUNCEMENT_TEXT, NOT_UPDATED_NOTICE_SENT_DATE

    cleaned = clean_transcription_text(text or "")

    try:
        last_date, last_text = get_latest_transcription()
    except:
        last_date, last_text = None, None

    subscribers = []
    try:
        subscribers = get_all_subscribers()
    except:
        pass

    # If same as yesterday -> send "not updated"
    if last_text and cleaned.strip() == last_text.strip():
        today = datetime.utcnow().strftime("%Y-%m-%d")

        if NOT_UPDATED_NOTICE_SENT_DATE != today:
            NOT_UPDATED_NOTICE_SENT_DATE = today

            sms_msg = (
                "ColorCodely update:\n\n"
                "The testing center has not updated today's color code yet."
            )
            email_subject = "ColorCodely update"
            email_body = (
                "Today's color code recording has not yet changed.\n"
                "We will notify you as soon as a new announcement is available.\n\n"
                "— ColorCodely"
            )

            for sub in subscribers:
                if sub.get("cell_number"):
                    async_task(send_sms, sub["cell_number"], sms_msg)
                if sub.get("email"):
                    async_task(send_email, sub["email"], email_subject, email_body)

        return

    # NEW announcement
    LATEST_ANNOUNCEMENT_TEXT = cleaned
    NOT_UPDATED_NOTICE_SENT_DATE = None

    try:
        save_daily_transcription(cleaned)
    except:
        pass

    sms_body = f"Today's color code announcement:\n\n{cleaned}"
    email_subject = "Today's ColorCodely announcement"
    email_body_template = (
        "Hello {name},\n\n"
        "Today's color code announcement:\n\n"
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
            async_task(
                send_email,
                email,
                email_subject,
                email_body_template.format(name=name, text=cleaned)
            )


# ----------------------------------------
# TWILIO POSTS RECORDING + TRANSCRIPTION HERE
# ----------------------------------------
@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    text = (
        request.form.get("TranscriptionText")
        or "No transcription text provided by Twilio."
    )
    async_task(_process_transcription, text)
    return ("", 204)


# ----------------------------------------
# DEV ENTRY
# ----------------------------------------
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True,
    )
