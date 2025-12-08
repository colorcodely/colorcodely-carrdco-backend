from flask import Flask, request, jsonify
import os
from sheets import append_row_to_sheet
from sms import send_sms
from emailer import send_email

app = Flask(__name__)

# Your Google Sheet ID (placeholder until we plug in your real one)
SPREADSHEET_ID = os.environ.get("SHEET_ID", "YOUR_SHEET_ID_HERE")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/submit", methods=["POST"])
def submit():
    try:
        data = request.json

        name = data.get("name")
        email = data.get("email")
        phone = data.get("phone")
        testing_center = data.get("testing_center")

        # Save to Google Sheets
        append_row_to_sheet(
            SPREADSHEET_ID,
            [name, email, phone, testing_center]
        )

        # Send welcome SMS
        sms_message = (
            f"Welcome to ColorCodely! You are subscribed to: {testing_center}. "
            f"You will receive daily color code notifications."
        )
        send_sms(phone, sms_message)

        # Send welcome Email
        email_subject = "Welcome to ColorCodely"
        email_body = (
            f"Hello {name},\n\n"
            f"You are now subscribed for daily testing center notifications.\n"
            f"Testing Center: {testing_center}\n\n"
            f"Thank you for using ColorCodely!"
        )
        send_email(email, email_subject, email_body)

        return jsonify({"status": "success"}), 200

    except Exception as e:
        # If ANYTHING goes wrong, log it and return error
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
