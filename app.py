import os
from datetime import datetime

from flask import Flask, request, jsonify, Response

from twilio.rest import Client

from sheets import append_row_to_sheet, get_sheets_service
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
# (Good enough for MVP; later you can persist this in Sheets if you want.)
LATEST_ANNOUNCEMENT_TEXT = None


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def get_form_field(data, *keys):
    """Safely pull the first non-empty value from a set of possible form keys."""
    for key in keys:
        if key in data and data[key].strip():
            return data[key].strip()
    return ""


def get_all_subscribers():
    """
    Read all subscriber rows from Sheet1.

    Expected columns per row:
        A: timestamp
        B: full_name
        C: email
        D: phone
        E: testing_center
    """
    subscribers = []
    try:
        service = get_sheets_service()
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=SPREADSHEET_ID, range="Sheet1!A1:E")
            .execute()
        )
        values = result.get("values", [])
        for row in values:
            # Skip rows that don't have at least email & phone
            if len(row) < 4:
                continue
            subscribers.append(
                {
                    "timestamp": row[0] if len(row) > 0 else "",
                    "name": row[1] if len(row) > 1 else "",
                    "email": row[2] if len(row) > 2 else "",
                    "phone": row[3] if len(row) > 3 else "",
                    "testing_center": row[4] if len(row) > 4 else "",
                }
            )
    except Exception as e:
        app.logger.exception("Error loading subscribers from sheet: %s", e)

    return subscribers


def log_transcription_to_sheet(call_sid, recording_url, transcription_text):
    """
    Log today's transcription in the same spreadsheet in a tab called 'Transcriptions'.
    (You can create this tab manually in Google Sheets if it doesn't exist yet.)
    Columns:
        A: timestamp (UTC ISO)
        B: Call SID
        C: Recording URL
        D: Transcription text
    """
    try:
        service = get_sheets_service()
        now = datetime.utcnow().isoformat()
        body = {
            "values": [[now, call_sid or "", recording_url or "", transcription_text]]
        }
        (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=SPREADSHEET_ID,
                range="Transcriptions!A1",
                valueInputOption="USER_ENTERED",
                body=body,
            )
            .execute()
        )
    except Exception as e:
        app.logger.exception("Failed to log transcription to sheet: %s", e)


# -----------------------------------------------------------------------------
# Health check
# -----------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# -----------------------------------------------------------------------------
# Carrd form submit endpoint
#   - Called by your Carrd "Send to URL" form (POST)
#   - Saves subscriber to Sheets
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

    timestamp = datetime.utcnow().isoformat()

    # Append the subscriber row to Sheet1
    try:
        row = [timestamp, full_name, email, phone, testing_center]
        append_row_to_sheet(SPREADSHEET_ID, row)
    except Exception as e:
        app.logger.exception("Failed to append subscriber row: %s", e)

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
# TwiML endpoint used for the outbound daily call
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
    try:
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
# Twilio Recording / Transcription callback
#   - Twilio calls this after the recorded call is complete.
#   - We grab TranscriptionText if available (or at least RecordingUrl),
#     log it to Sheets, update LATEST_ANNOUNCEMENT_TEXT,
#     then SMS + email all subscribers.
# -----------------------------------------------------------------------------
@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    global LATEST_ANNOUNCEMENT_TEXT

    form = request.form

    call_sid = form.get("CallSid")
    recording_url = form.get("RecordingUrl")
    transcription_text = form.get("TranscriptionText")

    if not transcription_text:
        # Fallback if Twilio didn't provide transcription text
        transcription_text = (
            "No transcription text was provided by Twilio "
            "(you may need to enable transcription for your account "
            "or process the recording manually)."
        )

    # Update in-memory latest announcement
    LATEST_ANNOUNCEMENT_TEXT = transcription_text

    # Log this transcription in Sheets (Transcriptions tab)
    log_transcription_to_sheet(call_sid, recording_url, transcription_text)

    # Load all subscribers from Sheet1
    subscribers = get_all_subscribers()

    sms_body = f"Today's color code announcement:\n\n{transcription_text}"
    email_subject = "Today's ColorCodely announcement"
    email_body_template = (
        "Hello {name},\n\n"
        "Here is today's color code announcement:\n\n"
        "{text}\n\n"
        "— ColorCodely"
    )

    for sub in subscribers:
        phone = sub.get("phone")
        email = sub.get("email")
        name = sub.get("name") or "there"

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
# Main entrypoint (for local testing, not used on Render with gunicorn)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
