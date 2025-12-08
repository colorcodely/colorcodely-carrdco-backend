import os
from datetime import datetime

from flask import Flask, request, jsonify, Response
from twilio.rest import Client

from sheets import add_subscriber, get_all_subscribers, save_daily_transcription, get_latest_transcription
from sms import send_sms
from emailer import send_email

app = Flask(__name__)

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


def get_form_field(data, *keys):
    """Helper to read Carrd form fields, trying multiple possible names."""
    for key in keys:
        if key in data and isinstance(data[key], str) and data[key].strip():
            return data[key].strip()
    return ""


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


def start_color_line_call():
    """
    Tell Twilio to call the Huntsville color line, record it,
    and send Twilio's recording/transcription callback to us.
    """
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


@app.route("/submit", methods=["POST"])
def submit():
    """
    Carrd form submit endpoint.

    - Saves subscriber to Google Sheets
    - If we **already** have a latest announcement, sends it in the welcome SMS/email
    - If we **don't** have any announcement yet, triggers a call once and tells them
      they'll get the first announcement as soon as it's available.
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

    # 2) Decide what to send based on whether we have any announcement yet
    if LATEST_ANNOUNCEMENT_TEXT is None:
        # Option A: First-ever signup or fresh system — trigger a call once
        try:
            start_color_line_call()
        except Exception as e:
            app.logger.exception("Failed to trigger initial call from submit: %s", e)

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
            "You’ll start receiving daily announcements by text and email "
            "as soon as the first recording is processed.\n\n"
            "— ColorCodely"
        )
    else:
        # We already have a recent announcement — send it right away
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
            "You'll continue receiving new announcements automatically each day.\n\n"
            "— ColorCodely"
        )

    # 3) Send welcome SMS + email
    try:
        send_sms(phone, sms_body)
    except Exception as e:
        app.logger.exception("Failed to send welcome SMS to %s: %s", phone, e)

    try:
        send_email(email, email_subject, email_body)
    except Exception as e:
        app.logger.exception("Failed to send welcome email to %s: %s", email, e)

    return jsonify({"status": "ok"})


@app.route("/twiml/dial_color_line", methods=["POST", "GET"])
def twiml_dial_color_line():
    """
    TwiML that tells Twilio to dial the Huntsville color line and record it.
    Twilio will invoke this when we start the outgoing call.
    """
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial record="record-from-answer-dual">
    <Number>{HUNTSVILLE_COLOR_LINE}</Number>
  </Dial>
</Response>
"""
    return Response(xml, mimetype="text/xml")


@app.route("/daily-call", methods=["POST"])
def daily_call():
    """
    Endpoint you point your Render Cron Job at.

    Each time this is called, we:
    - Start a Twilio call to the color line
    - Twilio then calls back to /twilio/recording-complete
    - /twilio/recording-complete decides whether it's a NEW announcement
      and whether to notify subscribers.
    """
    try:
        call_sid = start_color_line_call()
        return jsonify({"status": "started", "call_sid": call_sid})
    except Exception as e:
        app.logger.exception("Error starting daily call: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    """
    Twilio recording/transcription callback.

    Behavior:
    - If the transcription is the SAME as the latest saved one:
        -> Do NOT send yesterday's colors again
        -> Send a one-time "recording not updated yet" SMS/email for today
    - If the transcription is NEW:
        -> Save it to Google Sheets
        -> Update LATEST_ANNOUNCEMENT_TEXT
        -> Send today's announcement to all subscribers
    """
    global LATEST_ANNOUNCEMENT_TEXT, NOT_UPDATED_NOTICE_SENT_DATE

    form = request.form

    transcription_text = form.get("TranscriptionText")
    if not transcription_text:
        transcription_text = (
            "No transcription text was provided by Twilio. "
            "You may need to enable or configure transcription for recordings."
        )

    # 1) Compare with the last saved transcription in Sheets
    try:
        last_date, last_text = get_latest_transcription()
    except Exception as e:
        app.logger.exception("Failed to read latest transcription: %s", e)
        last_date, last_text = None, None

    is_same_as_last = False
    if last_text and transcription_text.strip() == last_text.strip():
        is_same_as_last = True

    # 2) Load all subscribers
    try:
        subscribers = get_all_subscribers()
    except Exception as e:
        app.logger.exception("Failed to load subscribers: %s", e)
        subscribers = []

    # 3) If it's the same as yesterday, don't resend it — send a "not updated yet" notice
    if is_same_as_last:
        today_str = datetime.utcnow().strftime("%Y-%m-%d")

        # Only send the "not updated yet" notice once per day
        if NOT_UPDATED_NOTICE_SENT_DATE == today_str:
            return ("", 204)

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
            "We attempted to retrieve today's color code announcement, but the "
            "recording has not been updated yet by the court.\n\n"
            "We'll keep checking and notify you as soon as there is a new "
            "announcement.\n\n"
            "— ColorCodely"
        )

        for sub in subscribers:
            phone = sub.get("cell_number")
            email = sub.get("email")
            name = sub.get("full_name") or "there"

            if phone:
                try:
                    send_sms(phone, info_sms)
                except Exception as e:
                    app.logger.exception("Failed to send 'not updated' SMS to %s: %s", phone, e)

            if email:
                try:
                    body = info_body_template.format(name=name)
                    send_email(email, info_subject, body)
                except Exception as e:
                    app.logger.exception("Failed to send 'not updated' email to %s: %s", email, e)

        return ("", 204)

    # 4) At this point, we have a **new** transcription 🎉
    LATEST_ANNOUNCEMENT_TEXT = transcription_text
    NOT_UPDATED_NOTICE_SENT_DATE = None  # reset for the next day

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
            try:
                send_sms(phone, sms_body)
            except Exception as e:
                app.logger.exception("Failed to send daily SMS to %s: %s", phone, e)

        if email:
            try:
                body = email_body_template.format(name=name, text=transcription_text)
                send_email(email, email_subject, body)
            except Exception as e:
                app.logger.exception("Failed to send daily email to %s: %s", email, e)

    return ("", 204)


if __name__ == "__main__":
    # Local testing only; Render uses gunicorn with PORT
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
