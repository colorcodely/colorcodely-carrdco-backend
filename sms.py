from twilio.rest import Client
import os

# Environment variables you'll configure in Render
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH")
TWILIO_FROM = os.getenv("TWILIO_FROM")

def send_sms(to_number, message):
    """Send an SMS message using Twilio."""
    try:
        client = Client(TWILIO_SID, TWILIO_AUTH)
        message = client.messages.create(
            body=message,
            from_=TWILIO_FROM,
            to=to_number
        )
        print("SMS sent:", message.sid)
    except Exception as e:
        print("Error sending SMS:", e)
        raise
