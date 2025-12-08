from flask import Flask, request, jsonify
from sheets import append_to_sheet
from sms import send_sms
from emailer import send_email
import os

app = Flask(__name__)

@app.route("/api/signup", methods=["POST"])
def signup():
    try:
        # Extract fields from Carrd form (POST)
        data = request.form

        full_name = data.get("full_name")
        email = data.get("email")
        phone = data.get("phone")
        testing_center = data.get("testing_center")
        color_code = data.get("color_code")

        if not all([full_name, email, phone, testing_center, color_code]):
            return jsonify({"status": "error", "message": "Missing required fields"}), 400

        # Store in Google Sheets
        append_to_sheet(full_name, email, phone, testing_center, color_code)

        # === SMS MESSAGE ===
        sms_message = (
            f"Welcome to ColorCodely!\n\n"
            f"You're subscribed to daily alerts for:\n"
            f"Testing Center: {testing_center}\n"
            f"Your Color Code: {color_code}\n\n"
            f"You will receive your daily notification each morning at 6:04 AM CST."
        )

        send_sms(phone, sms_message)
