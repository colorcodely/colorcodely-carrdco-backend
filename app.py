import os
import requests
import tempfile
from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse, Dial
from twilio.rest import Client
from openai import OpenAI
from collections import defaultdict

app = Flask(__name__)

# --------------------
# ENV / CLIENTS
# --------------------
TWILIO_SID = os.environ["TWILIO_SID"]
TWILIO_AUTH = os.environ["TWILIO_AUTH"]
FROM_NUMBER = os.environ["TWILIO_FROM"]
TARGET_NUMBER = os.environ["COLOR_CODE_NUMBER"]

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

twilio = Client(TWILIO_SID, TWILIO_AUTH)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# One-shot guards
PROCESSED_CALLS = set()

# Known color vocabulary
KNOWN_COLORS = {
    "amber","apple","aqua","banana","beige","black","blue","bone","bronze",
    "brown","burgundy","charcoal","chartreuse","cherry","chestnut","copper",
    "coral","cream","creme","crimson","eggplant","emerald","fuchsia","ginger",
    "gold","gray","green","hazel","indigo","ivory","jade","jasmine","khaki",
    "lavender","lemon","lilac","lime","magenta","mahogany","maroon","mauve",
    "mint","navy","olive","onyx","opal","orange","orchid","peach","pearl",
    "periwinkle","pink","platinum","plum","purple","raspberry","red","rose",
    "ruby","sage","sapphire","sienna","silver","tan","tangerine","teal",
    "turquoise","vanilla","violet","watermelon","white","yellow"
}

# --------------------
# TWIML: DIAL
# --------------------
@app.route("/twiml/dial_color_line", methods=["POST"])
def dial_color_line():
    resp = VoiceResponse()
    dial = Dial(
        record="record-from-answer-dual",
        timeLimit=75,
        recordingStatusCallback="/twilio/recording-complete",
        recordingStatusCallbackEvent="completed"
    )
    dial.number(TARGET_NUMBER)
    resp.append(dial)
    return Response(str(resp), mimetype="text/xml")

# --------------------
# RECORDING COMPLETE
# --------------------
@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    call_sid = request.form.get("CallSid")
    if not call_sid or call_sid in PROCESSED_CALLS:
        return ("ok", 200)

    PROCESSED_CALLS.add(call_sid)

    # Fetch all recordings for this call
    recordings = twilio.recordings.list(call_sid=call_sid)
    if not recordings:
        return ("no recordings", 200)

    # Pick the longest recording (the real announcement)
    longest = max(recordings, key=lambda r: int(r.duration or 0))
    audio_url = f"https://api.twilio.com{longest.uri.replace('.json', '.wav')}"

    # Download WAV
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        r = requests.get(audio_url, auth=(TWILIO_SID, TWILIO_AUTH))
        tmp.write(r.content)
        wav_path = tmp.name

    # Whisper transcription
    with open(wav_path, "rb") as audio_file:
        transcript = openai_client.audio.transcriptions.create(
            file=audio_file,
            model="whisper-1"
        )

    raw_text = transcript.text.lower()
    cleaned = clean_transcript(raw_text)

    send_email(cleaned)

    return ("ok", 200)

# --------------------
# CLEAN TRANSCRIPT
# --------------------
def clean_transcript(text):
    words = text.replace(",", " ").split()
    detected = sorted({w for w in words if w in KNOWN_COLORS})

    if "no" in words and "called" in words:
        return "No colors are being called today."

    if detected:
        return f"Colors called today: {', '.join(detected)}"

    return "Color announcement could not be confidently confirmed."

# --------------------
# EMAIL
# --------------------
def send_email(body):
    # Your existing email logic here
    print("EMAIL CONTENT:")
    print(body)

# --------------------
# HEALTH
# --------------------
@app.route("/")
def health():
    return "OK", 200
