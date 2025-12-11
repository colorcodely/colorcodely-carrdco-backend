from flask import Flask, request, jsonify, Response
from twilio.twiml.voice_response import VoiceResponse, Dial
import requests
import os
import openai
from sms import send_sms_to_all_subscribers
from emailer import send_email_to_all_subscribers
from sheets import store_announcement_in_sheet

app = Flask(__name__)

# -----------------------------
#  Configuration
# -----------------------------
TESTING_CENTER_NUMBER = "+12564277808"
OPENAI_API_KEY = os.environ.get("CHATGPT_API")
openai.api_key = OPENAI_API_KEY


# ---------------------------------------------------------
# 1) Twilio fetches this TwiML when making the outbound call
# ---------------------------------------------------------
@app.route("/twiml/dial_color_line", methods=["POST"])
def dial_color_line():
    response = VoiceResponse()

    dial = Dial(
        record="record-from-answer",
        recording_status_callback="https://colorcodely-carrdco-backend.onrender.com/twilio/recording-callback",
        timeout=20
    )
    dial.number(TESTING_CENTER_NUMBER)

    response.append(dial)
    return Response(str(response), mimetype="text/xml")


# ---------------------------------------------------------
# 2) Twilio calls this AFTER the call ends with the recording
# ---------------------------------------------------------
@app.route("/twilio/recording-callback", methods=["POST"])
def recording_callback():
    recording_url = request.form.get("RecordingUrl")

    if not recording_url:
        return "No recording found", 400

    # Twilio provides recording without file extension → append ".mp3"
    audio_url = recording_url + ".mp3"

    # Download the recording
    audio_data = requests.get(audio_url).content
    temp_filename = "/tmp/colorline_recording.mp3"

    with open(temp_filename, "wb") as f:
        f.write(audio_data)

    # Transcribe using Whisper via OpenAI
    try:
        with open(temp_filename, "rb") as audio_file:
            transcription = openai.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=audio_file
            )
        text = transcription.text.strip()

    except Exception as e:
        text = f"(Transcription failed: {str(e)})"

    # Save to Google Sheets
    try:
        store_announcement_in_sheet(text)
    except Exception as e:
        print("Sheets error:", e)

    # Notify subscribers via SMS
    try:
        send_sms_to_all_subscribers(text)
    except Exception as e:
        print("SMS error:", e)

    # Notify subscribers via Email
    try:
        send_email_to_all_subscribers(text)
    except Exception as e:
        print("Email error:", e)

    return "OK", 200


# ---------------------------------------------------------
# 3) Daily-call endpoint for cron job (Render runs this)
# ---------------------------------------------------------
@app.route("/daily-call", methods=["POST"])
def daily_call():
    """
    Render Cron Job triggers this endpoint every morning.
    It triggers the outbound call from Twilio to the testing center.
    """
    twilio_sid = os.environ.get("TWILIO_SID")
    twilio_auth = os.environ.get("TWILIO_AUTH")
    twilio_from = os.environ.get("TWILIO_FROM")

    url = f"https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}/Calls.json"

    payload = {
        "To": TESTING_CENTER_NUMBER,
        "From": twilio_from,
        "Url": "https://colorcodely-carrdco-backend.onrender.com/twiml/dial_color_line"
    }

    response = requests.post(url, data=payload, auth=(twilio_sid, twilio_auth))
    return jsonify({"twilio_response": response.json()})


# ---------------------------------------------------------
# 4) Carrd form submission handlers
# ---------------------------------------------------------
@app.route("/submit", methods=["POST"])
def submit_form():
    data = request.json
    return jsonify({"status": "received", "data": data})


@app.route("/store-sheets", methods=["POST"])
def store_sheets():
    data = request.json
    store_announcement_in_sheet(data.get("message", ""))
    return jsonify({"status": "stored"})


@app.route("/send-email", methods=["POST"])
def send_email():
    data = request.json
    message = data.get("message", "")
    send_email_to_all_subscribers(message)
    return jsonify({"status": "email sent"})


@app.route("/send-sms", methods=["POST"])
def send_sms():
    data = request.json
    message = data.get("message", "")
    send_sms_to_all_subscribers(message)
    return jsonify({"status": "sms sent"})


# ---------------------------------------------------------
# Home
# ---------------------------------------------------------
@app.route("/")
def home():
    return "ColorCodely Backend Running"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
