import os
import requests
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import openai
from google.oauth2 import service_account
from googleapiclient.discovery import build

openai.api_key = os.environ["OPENAI_API_KEY"]
TESTING_CENTER = os.environ["TESTING_CENTER"]

CENTER_CONFIG = {
    "AL_HSV_MUNICIPAL_COURT": {
        "sheet": "DailyTranscriptions",
        "location": "City of Huntsville, AL Municipal Court – Probation Office",
        "phone": "256-427-7808",
    },
    "AL_HSV_MCOAS": {
        "sheet": "MCOAS_DailyTranscriptions",
        "location": "Madison County Office of Alternative Sentencing",
        "phone": "256-533-8943",
    },
    "AL_MORGANCOUNTY": {
        "sheet": "AL_MorganCounty_DailyTranscriptions",
        "location": "Morgan County Court Referral Office",
        "phone": "256-560-6042",
    },
}

cfg = CENTER_CONFIG[TESTING_CENTER]
