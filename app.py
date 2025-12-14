import os
import logging
from datetime import date

from flask import Flask, request, Response, jsonify
from twilio.rest import Client
import requests

from sheets import save_daily_transcription, get_latest_transcription
from emailer import send_email

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def today_str():
    return date.today().strftime("%Y-%m-%d")


def already_transcribed_today():
    last_date, _ = get_latest_transcription()
    return last_date == today_str()


def get_required_env():
    vars = {
        "TWILIO_ACCOUNT_SID": os.environ.get("TWILIO_ACCOUNT_SID"),
        "TWILIO_AUTH_TOKEN": os.environ.get("TWILIO_AUTH_TOKEN"),
        "TWILIO_FROM_NUMBER": os.environ.get("TWILIO_FROM_NUMBER"),
        "TWILIO_TO_NUMBER": os.environ.get("TWILIO_TO_NUMBER"),
        "APP_BASE_URL": os.environ.get("APP_BASE_URL"),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
    }
    missing = [k for k, v in vars.items() if not v]
    return vars, missing


def transcribe_with_whisper(recording_url, env):
    audio = requests.get(
        recording_url,
        auth=(env["TWILIO_ACCOUNT_SID"], env["TWILIO_AUTH_TOKEN"]),
        timeout=30,
    )

    if audio.status_code != 200:
        raise RuntimeError("Failed to download recording")

    import openai
    openai.api_key = env["OPENAI_API_KEY"]

    response = openai.audio.transcriptions.create(
        file=("audio.wav", audio.content),
        model="gpt-4o-transcribe",
    )

    return response.text.strip()


# --------------------------------------------------
# Routes
# --------------------------------------------------

@app.route("/", methods=["GET"])
def health():
    return "OK", 200


@app.route("/daily-call", methods=["POST"])
def daily_call():
    env, missing = get_required_env()
    if missing:
        logging.error(f"Missing env vars: {missing}")
        return jsonify({"error": "Missing environment variables"}), 500

    if already_transcribed_today():
        logging.info("Already transcribed today — skipping call")
        return jsonify({"status": "skipped"}), 200

    twilio = Client(env["TWILIO_ACCOUNT_SID"], env["TWILIO_AUTH_TOKEN"])

    call = twilio.calls.create(
        to=env["TWILIO_TO_NUMBER"],
        from_=env["TWILIO_FROM_NUMBER"],
        url=f"{env['APP_BASE_URL']}/twiml/record",
        timeout=55,
    )

    logging.info(f"Call started: {call.sid}")
    return jsonify({"call_sid": call.sid}), 200


@app.route("/twiml/record", methods=["POST"])
def twiml_record():
    callback = f"{os.environ.get('APP_BASE_URL')}/twilio/recording-complete"

    return Response(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Record
        maxLength="120"
        playBeep="false"
        trim="trim-silence"
        recordingStatusCallback="{callback}"
        recordingStatusCallbackMethod="POST"
    />
    <Hangup/>
</Response>
""",
        mimetype="text/xml",
    )


@app.route("/twilio/recording-complete", methods=["POST"])
def recording_complete():
    env, missing = get_required_env()
    if missing:
        logging.error(f"Missing env vars at callback: {missing}")
        return ("", 500)

    if already_transcribed_today():
        logging.info("Callback ignored — already processed today")
        return ("", 204)

    recording_url = request.form.get("RecordingUrl")
    if not recording_url:
        logging.error("RecordingUrl missing")
        return ("", 400)

    try:
        transcription = transcribe_with_whisper(recording_url, env)
        save_daily_transcription(transcription)
        send_email(
            subject=f"Color Codes for {today_str()}",
            body=transcription,
        )
        logging.info("Transcription saved and emailed")
    except Exception as e:
        logging.exception("Processing failed")
        send_email(
            subject="ColorCodeLy Error",
            body=str(e),
        )
        return ("", 500)

    return ("", 204)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
