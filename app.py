import os
import tempfile
import requests
from flask import Flask, request, Response
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Dial

app = Flask(__name__)

# =========================
# Environment variables
# =========================

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Log missing vars but DO NOT crash
for name, val in {
    "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
    "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
    "TWILIO_FROM_NUMBER": TWILIO_FROM_NUMBER,
    "OPENAI_API_KEY": OPENAI_API_KEY,
}.items():
    if not val:
        print(f"⚠️ Missing env var: {name}")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# =========================
# One-shot guard
# =========================

ACTIVE_CALLS = set()

# =========================
# TwiML – dial ONCE
# =========================

@app.route("/twiml/dial_color_line", methods=["POST"])
def dial_color_line():
    call_sid = request.form.get("CallSid")

    if call_sid in ACTIVE_CALLS:
        print("🔁 Duplicate TwiML ignored:", call_sid)
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
# Recording finished → Whisper
# =========================

@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_sid = request.form.get("RecordingSid")
    call_sid = request.form.get("CallSid")

    if not recording_sid:
        return ("Missing RecordingSid", 400)

    print("🎧 Recording complete:", recording_sid)

    # Download recording
    audio_url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{TWILIO_ACCOUNT_SID}/Recordings/{recording_sid}.wav"
    )
    audio_resp = requests.get(audio_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))

    if audio_resp.status_code != 200:
        print("❌ Failed to download audio")
        return ("Audio download failed", 500)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_resp.content)
        audio_path = f.name

    transcript = run_whisper(audio_path)

    send_email(transcript)

    return ("OK", 204)

# =========================
# Whisper via raw HTTPS
# =========================

def run_whisper(audio_path):
    print("🧠 Running Whisper")

    with open(audio_path, "rb") as audio_file:
        resp = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}"
            },
            files={
                "file": audio_file,
                "model": (None, "whisper-1"),
                "language": (None, "en")
            },
            timeout=60
        )

    if resp.status_code != 200:
        print("❌ Whisper error:", resp.text)
        return "Transcription failed."

    return resp.json().get("text", "").strip()

# =========================
# Email (placeholder)
# =========================

def send_email(text):
    print("📧 EMAIL BODY:")
    print(text)
