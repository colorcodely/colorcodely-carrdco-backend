import os
import smtplib
from email.message import EmailMessage

# Environment variables (you'll set these in Render)
EMAIL_FROM = os.getenv("EMAIL_FROM")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = os.getenv("SMTP_PORT")  # We'll set this to 465 in Render
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

def send_email(to_email, subject, body):
    """Send an email using SMTP."""
    try:
        msg = EmailMessage()
        msg["From"] = EMAIL_FROM
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)

        # Connect to SMTP server securely
        with smtplib.SMTP_SSL(SMTP_SERVER, int(SMTP_PORT)) as smtp:
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(msg)

        print("Email sent to:", to_email)

    except Exception as e:
        print("Error sending email:", e)
        raise
