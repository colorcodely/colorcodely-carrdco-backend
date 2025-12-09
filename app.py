@app.route("/submit", methods=["POST", "HEAD"])
def submit():
    """
    Carrd form submit endpoint.

    - Carrd sends HEAD first → we must return 200 OK or Carrd shows a 502 error.
    - Then Carrd sends POST → actual subscriber data.
    """

    # Handle Carrd HEAD request safely
    if request.method == "HEAD":
        return ("", 200)

    global LATEST_ANNOUNCEMENT_TEXT

    form = request.form

    full_name = get_form_field(form, "full_name", "name", "Name")
    email = get_form_field(form, "email", "Email")
    phone = get_form_field(form, "phone", "cell", "cell_number", "Cell Number")
    testing_center = get_form_field(form, "testing_center", "Testing Center")

    if not email or not phone or not testing_center:
        return (
            jsonify({
                "status": "error",
                "message": "Missing required fields (email, phone, testing_center).",
            }),
            400,
        )

    # 1) Save to Google Sheets
    try:
        add_subscriber(full_name, email, phone, testing_center)
    except Exception as e:
        app.logger.exception("Failed to add subscriber: %s", e)

    # 2) Decide welcome message content
    if LATEST_ANNOUNCEMENT_TEXT is None:
        try:
            start_color_line_call()
        except Exception as e:
            app.logger.exception("Failed to trigger initial call: %s", e)

        sms_body = (
            "Welcome to ColorCodely alerts!\n\n"
            "You’re subscribed. We're calling the color code line now. "
            "You'll receive the latest announcement shortly."
        )
        email_subject = "Welcome to ColorCodely alerts"
        email_body = (
            f"Hi {full_name or ''},\n\n"
            "You're now subscribed to ColorCodely.\n\n"
            "We're fetching today's announcement now, and you'll receive it as soon as it's processed.\n\n"
            "— ColorCodely"
        )
    else:
        sms_body = (
            "Welcome to ColorCodely alerts!\n\n"
            "Here is the latest color code announcement:\n\n"
            f"{LATEST_ANNOUNCEMENT_TEXT}"
        )
        email_subject = "Welcome to ColorCodely – Latest Announcement"
        email_body = (
            f"Hi {full_name or ''},\n\n"
            "You're now subscribed to ColorCodely alerts.\n\n"
            "Here is the latest announcement:\n\n"
            f"{LATEST_ANNOUNCEMENT_TEXT}\n\n"
            "— ColorCodely"
        )

    # 3) Send SMS + email
    try:
        send_sms(phone, sms_body)
    except Exception as e:
        app.logger.exception("Failed to send welcome SMS: %s", e)

    try:
        send_email(email, email_subject, email_body)
    except Exception as e:
        app.logger.exception("Failed to send welcome email: %s", e)

    return jsonify({"status": "ok"}), 200
