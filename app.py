import os
import logging
import requests
import tempfile
from datetime import datetime

from flask import Flask, request, jsonify, Response
from twilio.rest import Client as TwilioClient

# --------------------------------------------------
# App + logging
# --------------------------------------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --------------------------------------------------
# Twilio client (ONLY dependency at runtime)
# --------------------------------------------------
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")
TWILIO_TO_NUMBER = os.environ.get("TWILIO_TO_NUMBER")

if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN]):
    raise RuntimeError("Twilio credentials missing")

twilio_client = TwilioClient(
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN
)

# --------------------------------------------------
# Health check
# --------------------------------------------------
@app.route("/", methods=["GET"])
def health():
    return "OK", 200

# --------------------------------------------------
# Trigger daily call
# --------------------------------------------------
@app.route("/daily-call", methods=["POST"])
def daily_call():
    call = twilio_client.calls.create(
        to=TWILIO_TO_NUMBER,
        from_=TWILIO_FROM_NUMBER,
        url="https://colorcodely-carrdco-backend.onrender.com/twiml/record",
        timeout=55,
        trim="trim-silence"
    )

    logging.info(f"Call started: {call.sid}")
    return jsonify({"call_sid": call.sid}), 200

# --------------------------------------------------
# TwiML: record audio
# --------------------------------------------------
@app.route("/twiml/record", methods=["POST"])
def twiml_record():
    return Response(
        """
        <Response>
            <Record
                maxLength="120"
                playBeep="false"
                trim="trim-silence"
                recordingStatusCallback="https://colorcodely-carrdco-backend.onrender.com/twilio/recording-complete"
                recordingStatusCallbackMethod="POST"
            />
            <Hangup/>
        </Response>
        """,
        mimetype="text/xml"
    )

# --------------------------------------------------
# Recording complete (NO OpenAI here)
# --------------------------------------------------
@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_url = request.form.get("RecordingUrl")
    call_sid = request.form.get("CallSid")

    if not recording_url:
        logging.error("Recording callback missing RecordingUrl")
        return "Missing RecordingUrl", 400

    logging.info("Recording completed")
    logging.info(f"Call SID: {call_sid}")
    logging.info(f"Recording URL: {recording_url}")

    # At this stage we only acknowledge receipt
    # Transcription is handled OUTSIDE this service
    return "OK", 200

# --------------------------------------------------
# Entrypoint
# --------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
