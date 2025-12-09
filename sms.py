import os
from twilio.rest import Client

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def send_sms(to_number: str, body: str):
    """
    Send an SMS using your plain Twilio phone number (not a Messaging Service).
    to_number must be in E.164 format like +12565551234
    """
    message = client.messages.create(
        to=to_number,
        from_=TWILIO_FROM_NUMBER,
        body=body,
    )
    print(f"SMS sent: {message.sid}")
