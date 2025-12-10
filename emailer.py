import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_SERVER = os.environ.get("SMTP_SERVER")          # smtp-relay.brevo.com
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))  # 587
SMTP_USERNAME = os.environ.get("SMTP_USERNAME")      # your Brevo login (9db6f9001@...)
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")      # the long Brevo password/API key
SMTP_FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL")  # e.g. colorcodely@gmail.com
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "ColorCodely Alerts")


def send_email(to_email: str, subject: str, body: str) -> None:
    """
    Send an email via Brevo using STARTTLS on port 587.
    """

    if not to_email:
        return

    if not (SMTP_SERVER and SMTP_PORT and SMTP_USERNAME and SMTP_PASSWORD and SMTP_FROM_EMAIL):
        # Safeguard: log but don't crash the app
        print("Email not sent: SMTP configuration is incomplete.")
        return

    # Build message
    msg = MIMEMultipart()
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        # NOTE: use SMTP + starttls(), NOT SMTP_SSL
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.sendmail(SMTP_FROM_EMAIL, [to_email], msg.as_string())

        print(f"Email sent to {to_email}")

    except Exception as e:
        # Log the error but don't raise, so it doesn't crash the worker
        print(f"Error sending email to {to_email}: {e}")
