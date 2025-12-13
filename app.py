import os
import tempfile
import requests
from flask import Flask, request, Response, jsonify
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Dial
import smtplib
from email.mime.text import MIMEText

app = Flask(__name__)

# =========================
# Environment variables
# =========================

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "ColorCodely")

ALERT_EMAIL = "officiallymattp@gmail.com"

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# =========================
# In-memory guards
# =========================

ACTIVE_CALLS = set()
PROCESSED_RECORDINGS = set()

# =========================
# HEALTH CHECK
# =========================

@app.route("/", methods=["GET"])
def health():
    return "OK", 200

# =========================
# CRON ENTRYPOINT
# =========================

@app.route("/daily-call", methods=["POST"])
def daily_call():
    print("⏰ Daily call triggered")

    call = twilio_client.calls.create(
        from_=TWILIO_FROM_NUMBER,
        to="+12564277808",
        url=f"{os.getenv('APP_BASE_URL')}/twiml/dial_color_line",
        record=True,
        recording_status_callback=f"{os.getenv('APP_BASE_URL')}/twilio/recording-complete",
        recording_status_callback_event=["completed"],
        timeout=55
    )

    return jsonify({"call_sid": call.sid, "status": "started"}), 200

# =========================
# TwiML – dial ONCE
# =========================

@app.route("/twiml/dial_color_line", methods=["POST"])
def dial_color_line():
    call_sid = request.form.get("CallSid")

    if call_sid in ACTIVE_CALLS:
        return Response("", status=204)

    ACTIVE_CALLS.add(call_sid)

    vr = VoiceResponse()
    dial = Dial(
        record="record-from-answer-dual",
        timeLimit=65
    )
    dial.number("+12564277808")
    vr.append(dial)

    return Response(str(vr), mimetype="text/xml")

# =========================
# Recording finished
# =========================

@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_sid = request.form.get("RecordingSid")

    if not recording_sid or recording_sid in PROCESSED_RECORDINGS:
        return ("Ignored", 204)

    PROCESSED_RECORDINGS.add(recording_sid)

    print("🎧 Recording complete:", recording_sid)

    audio_url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{TWILIO_ACCOUNT_SID}/Recordings/{recording_sid}.wav"
    )

    audio_resp = requests.get(
        audio_url,
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    )

    if audio_resp.status_code != 200:
        return ("Audio download failed", 500)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_resp.content)
        audio_path = f.name

    transcript = run_whisper(audio_path)
    send_email(transcript)

    return ("OK", 204)

# =========================
# Whisper transcription
# =========================

def run_whisper(audio_path):
    with open(audio_path, "rb") as audio:
        resp = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}"
            },
            files={
                "file": audio,
                "model": (None, "whisper-1"),
                "language": (None, "en")
            },
            timeout=60
        )

    if resp.status_code != 200:
        return "Transcription failed."

    return resp.json().get("text", "").strip()

# =========================
# Email
# =========================

def send_email(text):
    msg = MIMEText(text or "No transcription text returned.")
    msg["Subject"] = "Today's Color Code Announcement"
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    msg["To"] = ALERT_EMAIL

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)

    print("📧 Email sent")
