import os
import json
import tempfile
import datetime
from flask import Flask, request, jsonify

import requests
from twilio.rest import Client
import gspread
from google.oauth2.service_account import Credentials

# -----------------------------
# Environment variables
# -----------------------------
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM_NUMBER = os.environ["TWILIO_FROM_NUMBER"]

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]

# -----------------------------
# App setup
# -----------------------------
app = Flask(__name__)
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# -----------------------------
# Google Sheets
# -----------------------------
def get_sheets():
    creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    return sh.worksheet("daily_transcriptions")

# -----------------------------
# Utilities
# -----------------------------
def now_ct():
    return datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=-6))
    )

def format_message(day, date_str, colors):
    return (
        f"{day} {date_str}\n\n"
        "TESTING CENTER:\n"
        "City of Huntsville, AL Municipal Court Probation Office\n\n"
        "The color codes announced at 256-427-7808 are:\n"
        + ", ".join(colors)
    )

# -----------------------------
# Routes
# -----------------------------
@app.route("/", methods=["GET"])
def health():
    return "ok", 200

@app.route("/daily-call", methods=["POST"])
def daily_call():
    call = twilio_client.calls.create(
        to="+12564277808",
        from_=TWILIO_FROM_NUMBER,
        url="https://colorcodely-carrdco-backend.onrender.com/twiml/dial_color_line",
        record=True
    )
    return jsonify({"call_sid": call.sid, "status": "started"}), 200

@app.route("/twiml/dial_color_line", methods=["POST"])
def dial_color_line():
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Dial record='record-from-answer-dual' timeLimit='70'>"
        "<Number>+12564277808</Number>"
        "</Dial>"
        "</Response>"
    ), 200, {"Content-Type": "text/xml"}

@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_url = request.form.get("RecordingUrl")
    call_sid = request.form.get("CallSid")

    if not recording_url:
        return "", 204

    audio_url = f"{recording_url}.wav"
    audio_resp = requests.get(
        audio_url,
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    )

    if audio_resp.status_code != 200:
        return "", 204

    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        f.write(audio_resp.content)
        f.flush()

        # --- Whisper via raw HTTP ---
        whisper_resp = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}"
            },
            files={
                "file": open(f.name, "rb")
            },
            data={
                "model": "whisper-1"
            }
        )

    if whisper_resp.status_code != 200:
        return "", 204

    transcript_text = whisper_resp.json().get("text", "").lower()

    COLORS = [
        "amber","apple","aqua","banana","beige","black","blue","bone","bronze","brown",
        "burgundy","charcoal","chartreuse","cherry","chestnut","copper","coral","cream",
        "crimson","eggplant","emerald","fuchsia","ginger","gold","gray","green","hazel",
        "indigo","ivory","jade","khaki","lavender","lemon","lilac","lime","magenta",
        "mahogany","maroon","mauve","mint","navy","olive","onyx","opal","orange","orchid",
        "peach","pearl","pink","platinum","plum","purple","raspberry","red","rose","ruby",
        "sage","sapphire","silver","tan","teal","turquoise","vanilla","violet",
        "watermelon","white","yellow"
    ]

    detected = [c for c in COLORS if c in transcript_text]

    now = now_ct()
    day = now.strftime("%A").upper()
    date_str = now.strftime("%m/%d/%Y")

    sheet = get_sheets()
    sheet.append_row([
        date_str,
        now.strftime("%H:%M:%S"),
        call_sid,
        ", ".join(detected),
        transcript_text
    ])

    return "", 204

# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
