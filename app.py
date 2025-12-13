import os
import json
import tempfile
import requests
from flask import Flask, request, Response
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Dial
from openai import OpenAI

app = Flask(__name__)

# =========================
# Environment variables
# =========================

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APP_BASE_URL = os.getenv("APP_BASE_URL")

# Fail gracefully (log, don’t crash)
missing = []
for name, val in {
    "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
    "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
    "TWILIO_FROM_NUMBER": TWILIO_FROM_NUMBER,
    "OPENAI_API_KEY": OPENAI_API_KEY,
}.items():
    if not val:
        missing.append(name)

if missing:
    print("⚠️ Missing environment variables:", ", ".join(missing))

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# One-shot recording guard
# =========================

ACTIVE_CALLS = set()

# =========================
# Known color vocabulary
# =========================

KNOWN_COLORS = {
    "amber","apple","aqua","banana","beige","black","blue","bone","bronze","brown",
    "burgundy","charcoal","chartreuse","cherry","chestnut","copper","coral","cream",
    "creme","crimson","eggplant","emerald","fuchsia","ginger","gold","gray","green",
    "hazel","indigo","ivory","jade","jasmine","khaki","lavender","lemon","lilac",
    "lime","magenta","mahogany","maroon","mauve","mint","navy","olive","onyx","opal",
    "orange","orchid","peach","pearl","periwinkle","pink","platinum","plum","purple",
    "raspberry","red","rose","ruby","sage","sapphire","sienna","silver","tan",
    "tangerine","teal","turquoise","vanilla","violet","watermelon","white","yellow"
}

# =========================
# TwiML: Dial once, record once
# =========================

@app.route("/twiml/dial_color_line", methods=["POST"])
def dial_color_line():
    call_sid = request.form.get("CallSid")

    if call_sid in ACTIVE_CALLS:
        print("🔁 Duplicate TwiML request ignored:", call_sid)
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
# Recording complete → Whisper
# =========================

@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_sid = request.form.get("RecordingSid")
    call_sid = request.form.get("CallSid")

    if not recording_sid or not call_sid:
        return ("Missing data", 400)

    print("🎧 Recording complete:", recording_sid)

    # Download audio
    audio_url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Recordings/{recording_sid}.wav"
    auth = (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    audio_resp = requests.get(audio_url, auth=auth)

    if audio_resp.status_code != 200:
        print("❌ Failed to download audio")
        return ("Download failed", 500)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_resp.content)
        audio_path = f.name

    # Whisper transcription
    transcript = openai_client.audio.transcriptions.create(
        file=open(audio_path, "rb"),
        model="whisper-1",
        language="en"
    ).text.lower()

    cleaned = clean_transcript(transcript)

    send_email(cleaned)

    return ("OK", 204)

# =========================
# Transcript cleanup
# =========================

def clean_transcript(text):
    words = text.replace(",", " ").replace(".", " ").split()
    found = [w for w in words if w in KNOWN_COLORS]

    if not found:
        return "No colors confidently detected."

    unique = sorted(set(found))
    return "Colors called today: " + ", ".join(unique)

# =========================
# Email (stub – uses your existing SMTP code)
# =========================

def send_email(body):
    print("📧 EMAIL CONTENT:")
    print(body)
