import os
from datetime import datetime
from threading import Thread

from flask import Flask, request, jsonify, Response
from twilio.rest import Client

from sheets import (
    add_subscriber,
    get_all_subscribers,
    save_daily_transcription,
    get_latest_transcription,
)
from sms import send_sms
from emailer import send_email

app = Flask(__name__)

# ----------------------------------------
# ENV / CONFIG
# ----------------------------------------
SPREADSHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").rstrip("/")

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

HUNTSVILLE_COLOR_LINE = "+12564277808"

LATEST_ANNOUN
