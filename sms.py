from twilio.rest import Client
import os

# Environment variables from Render
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM = os.getenv("TWILIO_FROM_NUMBER")


def send_sms(to_number: str, message: str):
    """Send an SMS using Twilio."""
    if not (TWILIO_SID and TWILIO_AUTH and TWILIO_FROM):
        raise ValueError("Twilio environment variables are not fully set.")

    client = Client(TWILIO_SID, TWILIO_AUTH)
    msg = client.messages.create(
        body=message,
        from_=TWILIO_FROM,
        to=to_number,
    )
    print("SMS sent:", msg.sid)
