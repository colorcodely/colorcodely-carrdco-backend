def color_day_notification(
    date_str,
    testing_center,
    announcement_phone,
    color_codes
):
    """
    Standard notification for days when color codes ARE announced.
    Email + SMS friendly.
    """

    subject = "ColorCodely Notification for City of Huntsville, AL Municipal Court Probation Office"

    body = f"""
Color Code Notification – Powered by ColorCodely!

📅 DATE: {date_str}

🏛️ TESTING CENTER: {testing_center}

📞 ANNOUNCEMENT PHONE: {announcement_phone}

🎨 COLOR CODES:
{color_codes}

Please report to drug screen if your color is called.
"""

    return subject.strip(), body.strip()


def no_color_day_notification(
    date_str,
    testing_center,
    announcement_phone
):
    """
    Notification for days when NO color codes are announced
    (e.g., holidays or testing center closure).
    """

    subject = "ℹ️ ColorCodely Update — No Color Codes Announced Today"

    body = f"""
Color Code Update – Powered by ColorCodely!

📅 DATE: {date_str}

🏛️ TESTING CENTER: {testing_center}

📞 ANNOUNCEMENT PHONE: {announcement_phone}

🚫 COLOR CODES:
No color codes were announced today.

ℹ️ This typically indicates the testing center is closed or no testing is required for today.
Please follow your probation instructions and resume checking on the next scheduled day.
"""

    return subject.strip(), body.strip()
