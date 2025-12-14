import os
import json
import datetime
import tempfile
import requests
from flask import Flask, request, jsonify, Response
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Dial
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials
import smtplib
from email.message import EmailMessage

# --------------------
# App init
# --------------------
app = Flask(__name__)

# --------------------
# Environment
# --------------------
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM_NUMBER = os.environ["TWILIO_FROM_NUMBER"]

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_CREDS_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]

SMTP_SERVER = os.environ["SMTP_SERVER"]
SMTP_PORT = int(os.environ["SMTP_PORT"])
SMTP_USERNAME = os.environ["SMTP_USERNAME"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
SMTP_FROM_EMAIL = os.environ["SMTP_FROM_EMAIL"]
SMTP_FROM_NAME = os.environ["SMTP_FROM_NAME"]

APP_BASE_URL = os.environ["APP_BASE_URL"]

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# --------------------
# Google Sheets
# --------------------
def get_gsheets():
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)

# --------------------
# Email
# --------------------
def send_email(to_email, subject, body):
    msg = EmailMessage()
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)

# --------------------
# DAILY CALL TRIGGER
# --------------------
@app.route("/daily-call", methods=["POST"])
def daily_call():
    call = twilio_client.calls.create(
        from_=TWILIO_FROM_NUMBER,
        to="+12564277808",
        url=f"{APP_BASE_URL}/twiml/dial_color_line",
        record=True,
        recording_status_callback=f"{APP_BASE_URL}/twilio/recording-complete",
        recording_status_callback_event=["completed"],
        timeout=55
    )
    return jsonify({"call_sid": call.sid, "status": "started"})

# --------------------
# TWIML
# --------------------
@app.route("/twiml/dial_color_line", methods=["POST"])
def dial_color_line():
    resp = VoiceResponse()
    dial = Dial(record="record-from-answer-dual", timeLimit=65)
    dial.number("+12564277808")
    resp.append(dial)
    return Response(str(resp), mimetype="text/xml")

# --------------------
# RECORDING CALLBACK
# --------------------
@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    recording_url = request.form.get("RecordingUrl") + ".wav"
    call_sid = request.form.get("CallSid")

    # Download audio
    audio = requests.get(recording_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)).content
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        f.write(audio)
        f.flush()

        transcript = openai_client.audio.transcriptions.create(
            file=open(f.name, "rb"),
            model="gpt-4o-transcribe"
        )

    text = transcript.text.strip()

    # Extract colors (simple deterministic approach)
    COLOR_LIST = [
        "amber","apple","aqua","banana","beige","black","blue","bone","bronze","brown",
        "burgundy","charcoal","chartreuse","cherry","chestnut","copper","coral","cream",
        "crimson","eggplant","emerald","fuchsia","ginger","gold","gray","green","hazel",
        "indigo","ivory","jade","khaki","lavender","lemon","lilac","lime","magenta",
        "mahogany","maroon","mauve","mint","navy","olive","onyx","opal","orange","orchid",
        "peach","pearl","periwinkle","pink","platinum","plum","purple","raspberry","red",
        "rose","ruby","sage","sapphire","sienna","silver","tan","teal","turquoise",
        "vanilla","violet","watermelon","white","yellow"
    ]

    found = sorted({c for c in COLOR_LIST if c in text.lower()})
    colors = ", ".join(found).upper() if found else "NONE DETECTED"

    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    # Save to Google Sheets
    gc = get_gsheets()
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    sheet = sh.worksheet("daily_transcriptions")

    sheet.append_row([
        date_str,
        time_str,
        call_sid,
        colors,
        "HIGH" if found else "LOW",
        text
    ])

    # Email subscribers
    subs = sh.worksheet("subscribers").get_all_records()
    day_line = now.strftime("%A").upper() + " " + now.strftime("%m/%d/%Y")

    body = (
        f"{day_line}\n\n"
        f"TESTING CENTER: City of Huntsville, AL Municipal Court Probation Office\n\n"
        f"The color codes announced at 256-427-7808 are:\n"
        f"{colors}\n"
    )

    for s in subs:
        if s.get("email"):
            send_email(
                s["email"],
                f"Color Code Update — {day_line}",
                body
            )

    return ("", 204)

# --------------------
# Health check
# --------------------
@app.route("/")
def index():
    return "OK", 200
