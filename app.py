import os
from datetime import datetime

from flask import Flask, request, jsonify, Response
from twilio.rest import Client

from sheets import add_subscriber, get_all_subscribers, save_daily_transcription
from sms import send_sms
from emailer import send_email

# -----------------------------------------------------------------------------
# Flask app setup
# -----------------------------------------------------------------------------
app = Flask(__name__)

# Environment variables
SPREADSHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").rstrip("/")

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")

# Twilio REST client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# The Huntsville color code announcement line
HUNTSVILLE_COLOR_LINE = "+12564277808"

# In-memory cache of the latest announcement text
LATEST_ANNOUNCEMENT_TEXT = None


# -----------------------------------------------------------------------------
# Helper to safely pull fields from Carrd form
# -----------------------------------------------------------------------------
def get_form_field(data, *keys):
    """Return the first non-empty field among the given keys."""
    for key in keys:
        if key in data and isinstance(data[key], str) and data[key].strip():
            return data[key].strip()
    return ""


# -----------------------------------------------------------------------------
# Health check
# -----------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# -----------------------------------------------------------------------------
# Carrd form submit endpoint
#   - Called by Carrd "Send to URL" form (POST)
#   - Saves subscriber to Google Sheets
#   - Sends welcome SMS + email
#   - If we already have today's announcement, include it
# -----------------------------------------------------------------------------
@app.route("/submit", methods=["POST"])
def submit():
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

    # Store subscriber in the Subscribers sheet
    try:
        add_subscriber(full_name, email, phone, testing_center)
    except Exception as e:
        app.logger.exception("Failed to add subscriber: %s", e)

    # Build welcome messages
    if LATEST_ANNOUNCEMENT_TEXT:
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
    else:
        sms_body = (
            "Welcome to ColorCodely alerts!\n\n"
            "You’re subscribed and will begin receiving daily "
            "color code announcements after the next recording is processed."
        )
        email_subject = "Welcome to ColorCodely alerts"
        email_body = (
            f"Hi {full_name or ''},\n\n"
            "Thanks for subscribing to ColorCodely.\n\n"
            "You’ll start receiving daily color code announcements "
            "by text and email as soon as the next recording is captured.\n\n"
            "— ColorCodely"
        )

    # Send SMS
    try:
        send_sms(phone, sms_body)
    except Exception as e:
        app.logger.exception("Failed to send welcome SMS: %s", e)

    # Send Email
    try:
        send_email(email, email_subject, email_body)
    except Exception as e:
        app.logger.exception("Failed to send welcome email: %s", e)

    return jsonify({"status": "ok"})


# -----------------------------------------------------------------------------
# TwiML endpoint for outbound daily call
#   Twilio hits this when we start the call from /daily-call.
#   It tells Twilio: dial the Huntsville line and record the call.
# -----------------------------------------------------------------------------
@app.route("/twiml/dial_color_line", methods=["POST", "GET"])
def twiml_dial_color_line():
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial record="record-from-answer-dual">
    <Number>{HUNTSVILLE_COLOR_LINE}</Number>
  </Dial>
</Response>
"""
    return Response(xml, mimetype="text/xml")


# -----------------------------------------------------------------------------
# Daily call trigger endpoint
#   - Called by Render Cron Job every day at 6:04 AM CST
#   - Starts an outbound call from your Twilio number to the Huntsville line
#   - Twilio records the call and later hits /twilio/recording-complete
# -----------------------------------------------------------------------------
@app.route("/daily-call", methods=["POST"])
def daily_call():
    if not APP_BASE_URL:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "APP_BASE_URL is not set in environment variables.",
                }
            ),
            500,
        )

    try:
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

        return jsonify({"status": "started", "call_sid": call.sid})
    except Exception as e:
        app.logger.exception("Error starting daily call: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# -----------------------------------------------------------------------------
# Twilio recording/transcription callback
#   - Twilio calls this after the recorded call is complete.
#   - We grab TranscriptionText if available (or fallback),
#     save it in DailyTranscriptions, update in-memory latest text,
#     and SMS+email all subscribers.
# -----------------------------------------------------------------------------
@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    global LATEST_ANNOUNCEMENT_TEXT

    form = request.form

    call_sid = form.get("CallSid")
    recording_url = form.get("RecordingUrl")
    transcription_text = form.get("TranscriptionText")

    if not transcription_text:
        transcription_text = (
            "No transcription text was provided by Twilio. "
            "You may need to enable or configure transcription for recordings."
        )

    # Update in-memory latest announcement
    LATEST_ANNOUNCEMENT_TEXT = transcription_text

    # Save to the DailyTranscriptions sheet (date + text)
    try:
        save_daily_transcription(transcription_text)
    except Exception as e:
        app.logger.exception("Failed to save daily transcription: %s", e)

    # Load all subscribers
    try:
        subscribers = get_all_subscribers()
    except Exception as e:
        app.logger.exception("Failed to load subscribers: %s", e)
        subscribers = []

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

        # SMS
        if phone:
            try:
                send_sms(phone, sms_body)
            except Exception as e:
                app.logger.exception("Failed to send daily SMS to %s: %s", phone, e)

        # Email
        if email:
            try:
                body = email_body_template.format(name=name, text=transcription_text)
                send_email(email, email_subject, body)
            except Exception as e:
                app.logger.exception("Failed to send daily email to %s: %s", email, e)

    # Twilio just needs a 2xx response
    return ("", 204)


# -----------------------------------------------------------------------------
# Main entrypoint (for local testing)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
