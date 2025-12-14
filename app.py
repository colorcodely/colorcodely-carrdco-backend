# app.py
import os
import json
import time
import hashlib
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request, Response

try:
    # Twilio is only needed to generate TwiML. If it's not installed yet, the server still boots.
    from twilio.twiml.voice_response import VoiceResponse, Dial
except Exception:  # pragma: no cover
    VoiceResponse = None
    Dial = None


# -------------------------
# Basic app + logging
# -------------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("colorcodely")


# -------------------------
# Config (all via env vars)
# -------------------------
TZ_NAME = os.getenv("TZ_NAME", "America/Chicago")
TZ = ZoneInfo(TZ_NAME)

# The number Twilio should dial to reach the recorded announcement line.
# Example: +1256xxxxxxx
COLOR_LINE_NUMBER = os.getenv("COLOR_LINE_NUMBER", "").strip()

# How long to let the dial attempt ring before giving up
DIAL_TIMEOUT_SECONDS = int(os.getenv("DIAL_TIMEOUT_SECONDS", "55"))

# Safety cap for a single call, in seconds (Twilio may still end earlier)
CALL_HARD_LIMIT_SECONDS = int(os.getenv("CALL_HARD_LIMIT_SECONDS", "180"))

# Email subject prefix
EMAIL_SUBJECT_PREFIX = os.getenv("EMAIL_SUBJECT_PREFIX", "Color Code")

# OpenAI (we do NOT import the OpenAI Python SDK to avoid Render/httpx proxy issues)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "whisper-1").strip()

# State file (persists across requests; may reset on redeploy/restart)
STATE_PATH = os.getenv("STATE_PATH", "/tmp/colorcodely_state.json")

# Prevent spam: if today’s transcript text matches what we already sent today, skip sending again
DEDUP_SAME_DAY = os.getenv("DEDUP_SAME_DAY", "true").lower() in ("1", "true", "yes", "y")

# Optional: if you still want to allow “check again” later in the day (every 15 min via scheduler),
# this will still send ONLY if the transcript text is different from the last one we emailed.
ALLOW_MULTIPLE_PER_DAY_IF_CHANGED = os.getenv("ALLOW_MULTIPLE_PER_DAY_IF_CHANGED", "true").lower() in (
    "1",
    "true",
    "yes",
    "y",
)

# Optional: if Twilio posts callback multiple times for the same recording, skip by RecordingSid
DEDUP_RECORDING_SID = os.getenv("DEDUP_RECORDING_SID", "true").lower() in ("1", "true", "yes", "y")


# -------------------------
# Helpers: state
# -------------------------
def _load_state() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
    except Exception as e:
        log.warning("Could not save state: %s", e)


def _today_key() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _absolute_url(path: str) -> str:
    # request.url_root ends with "/"
    root = request.url_root.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return root + path


# -------------------------
# Helpers: email (uses your existing emailer.py)
# -------------------------
def _send_email(subject: str, body: str) -> None:
    """
    Uses your existing emailer.py without changing your naming conventions.
    We try a few common function signatures so you don’t have to rename anything.
    """
    try:
        import emailer  # type: ignore
    except Exception as e:
        log.error("emailer.py not importable: %s", e)
        return

    # Try common patterns
    candidates = [
        ("send_email", (subject, body)),
        ("send_email", (body, subject)),
        ("send", (subject, body)),
        ("send", (body, subject)),
        ("send_mail", (subject, body)),
        ("send_mail", (body, subject)),
    ]

    for fn_name, args in candidates:
        fn = getattr(emailer, fn_name, None)
        if callable(fn):
            try:
                fn(*args)
                log.info("Email sent via emailer.%s", fn_name)
                return
            except TypeError:
                continue
            except Exception as e:
                log.error("emailer.%s failed: %s", fn_name, e)
                return

    log.error(
        "No compatible email function found in emailer.py. "
        "Expected one of: send_email / send / send_mail"
    )


# -------------------------
# Helpers: sheets (uses your existing sheets.py)
# -------------------------
def _write_to_sheets(payload: dict) -> None:
    """
    Best-effort: uses your existing sheets.py if present.
    We do NOT require a specific function name; we try common ones.
    """
    try:
        import sheets  # type: ignore
    except Exception as e:
        log.warning("sheets.py not importable (continuing anyway): %s", e)
        return

    # Common patterns we’ll attempt (best effort, no breaking)
    candidates = [
        ("append_row", (payload,)),
        ("append", (payload,)),
        ("log", (payload,)),
        ("write", (payload,)),
        ("write_row", (payload,)),
    ]

    for fn_name, args in candidates:
        fn = getattr(sheets, fn_name, None)
        if callable(fn):
            try:
                fn(*args)
                log.info("Logged to Google Sheets via sheets.%s", fn_name)
                return
            except TypeError:
                continue
            except Exception as e:
                log.warning("sheets.%s failed (continuing): %s", fn_name, e)
                return


# -------------------------
# Helpers: Twilio recording download + transcription
# -------------------------
def _download_twilio_recording(recording_url: str) -> bytes:
    """
    Twilio RecordingUrl is typically a Twilio API URL that requires HTTP Basic Auth (Account SID + Auth Token).
    We read them via env if present; if not, we still try unauthenticated.
    """
    tw_sid = os.getenv("TWILIO_SID", "").strip()
    tw_auth = os.getenv("TWILIO_AUTH", "").strip()

    headers = {"User-Agent": "colorcodely/1.0"}
    auth = (tw_sid, tw_auth) if (tw_sid and tw_auth) else None

    # Twilio RecordingUrl is often without extension; adding .mp3 usually works.
    urls_to_try = []
    ru = recording_url.strip()
    if ru:
        urls_to_try.append(ru)
        if not ru.endswith(".mp3"):
            urls_to_try.append(ru + ".mp3")
        if not ru.endswith(".wav"):
            urls_to_try.append(ru + ".wav")

    last_err = None
    for url in urls_to_try:
        try:
            r = requests.get(url, headers=headers, auth=auth, timeout=30)
            r.raise_for_status()
            return r.content
        except Exception as e:
            last_err = e
            continue

    raise RuntimeError(f"Could not download recording from Twilio. Last error: {last_err}")


def _transcribe_audio(audio_bytes: bytes) -> str:
    """
    Calls OpenAI Audio Transcriptions endpoint directly (no Python SDK)
    to avoid the Render/openai/httpx proxies mismatch.
    """
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is missing in environment variables")

    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    files = {
        "file": ("audio.mp3", audio_bytes, "audio/mpeg"),
    }
    data = {
        "model": OPENAI_TRANSCRIBE_MODEL,
        "response_format": "text",
        # You can optionally set language="en" if you want:
        # "language": "en",
    }

    r = requests.post(url, headers=headers, files=files, data=data, timeout=90)
    r.raise_for_status()
    return (r.text or "").strip()


def _normalize_transcript(text: str) -> str:
    return " ".join((text or "").strip().split()).lower()


# -------------------------
# Routes
# -------------------------
@app.get("/healthz")
def healthz():
    return {"ok": True, "date": _today_key(), "tz": TZ_NAME}, 200


@app.post("/twiml/dial_color_line")
def twiml_dial_color_line():
    """
    This endpoint must return TwiML ONCE and must NOT re-enter itself.
    We use <Dial record="record-from-answer-dual"> instead of <Record> without action,
    which was causing the looping behavior.
    """
    if VoiceResponse is None:
        return Response("Twilio TwiML library not installed", status=500, mimetype="text/plain")

    if not COLOR_LINE_NUMBER:
        # Fail gracefully with TwiML hangup (prevents weird retries)
        vr = VoiceResponse()
        vr.say("Configuration error. Color line number is not set.")
        vr.hangup()
        return Response(str(vr), status=200, mimetype="text/xml")

    vr = VoiceResponse()

    dial = Dial(
        timeout=DIAL_TIMEOUT_SECONDS,
        # Record both sides from answer; sends RecordingSid/RecordingUrl to callback
        record="record-from-answer-dual",
        recording_status_callback=_absolute_url("/twilio/recording-complete"),
        recording_status_callback_method="POST",
        trim="trim-silence",
        time_limit=CALL_HARD_LIMIT_SECONDS,
    )
    dial.number(COLOR_LINE_NUMBER)
    vr.append(dial)
    vr.hangup()

    return Response(str(vr), status=200, mimetype="text/xml")


@app.post("/twilio/recording-complete")
def twilio_recording_complete():
    """
    Twilio calls this once the recording is available.
    We download recording, transcribe, and send a single email (dedup protected).
    """
    form = request.form or {}
    call_sid = (form.get("CallSid") or "").strip()
    recording_sid = (form.get("RecordingSid") or "").strip()
    recording_url = (form.get("RecordingUrl") or "").strip()
    recording_duration = (form.get("RecordingDuration") or "").strip()

    state = _load_state()
    today = _today_key()

    if DEDUP_RECORDING_SID and recording_sid:
        already = state.get("processed_recording_sids", [])
        if recording_sid in already:
            log.info("Skipping duplicate callback for RecordingSid=%s", recording_sid)
            return ("ok", 200)
        # Keep list from growing forever
        already = (already + [recording_sid])[-200:]
        state["processed_recording_sids"] = already
        _save_state(state)

    if not recording_url:
        log.warning("No RecordingUrl received from Twilio (CallSid=%s RecordingSid=%s)", call_sid, recording_sid)
        return ("missing RecordingUrl", 200)

    try:
        audio = _download_twilio_recording(recording_url)
        transcript = _transcribe_audio(audio)
    except Exception as e:
        log.exception("Recording processing failed: %s", e)
        # Best-effort: email the error so you know it happened
        subject = f"{EMAIL_SUBJECT_PREFIX} — ERROR ({today})"
        body = (
            f"Date: {today} ({TZ_NAME})\n"
            f"CallSid: {call_sid}\n"
            f"RecordingSid: {recording_sid}\n"
            f"RecordingUrl: {recording_url}\n"
            f"RecordingDuration: {recording_duration}\n\n"
            f"ERROR:\n{e}\n"
        )
        _send_email(subject, body)
        return ("error emailed", 200)

    normalized = _normalize_transcript(transcript)
    transcript_hash = _sha(normalized)

    last_sent_date = state.get("last_sent_date")
    last_sent_hash = state.get("last_sent_hash")

    # Dedup rules:
    # - If it's the same day and transcript matches what we already sent today => skip
    if DEDUP_SAME_DAY and last_sent_date == today and last_sent_hash == transcript_hash:
        log.info("Skipping duplicate transcript (same day, same content).")
        return ("duplicate skipped", 200)

    # If user allows multiple per day only when changed, we already handled with hash comparison.
    # If they disallow, block after first successful send of the day.
    if not ALLOW_MULTIPLE_PER_DAY_IF_CHANGED and last_sent_date == today:
        log.info("Skipping additional send (multiple per day disabled).")
        return ("already sent today", 200)

    subject = f"{EMAIL_SUBJECT_PREFIX} — {today}"
    body = (
        f"Date: {today} ({TZ_NAME})\n"
        f"CallSid: {call_sid}\n"
        f"RecordingSid: {recording_sid}\n"
        f"RecordingDuration: {recording_duration}\n\n"
        f"TRANSCRIPT:\n{transcript}\n"
    )

    _send_email(subject, body)

    # Best-effort log to Sheets
    _write_to_sheets(
        {
            "date": today,
            "call_sid": call_sid,
            "recording_sid": recording_sid,
            "recording_duration": recording_duration,
            "recording_url": recording_url,
            "transcript": transcript,
            "transcript_hash": transcript_hash,
            "timestamp": datetime.now(TZ).isoformat(),
        }
    )

    # Update state
    state["last_sent_date"] = today
    state["last_sent_hash"] = transcript_hash
    state["last_sent_transcript_preview"] = transcript[:2000]
    _save_state(state)

    return ("sent", 200)


# -------------------------
# Local dev entrypoint
# -------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
