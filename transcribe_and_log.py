import os
import requests
import tempfile
from openai import OpenAI
from sheets import save_daily_transcription

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
RECORDING_URL = os.environ["TWILIO_RECORDING_URL"]

client = OpenAI(api_key=OPENAI_API_KEY)


def download_recording(url: str) -> str:
    """
    Downloads a Twilio recording and returns local file path
    """
    response = requests.get(
        f"{url}.wav",
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        timeout=60,
    )
    response.raise_for_status()

    fd, path = tempfile.mkstemp(suffix=".wav")
    with os.fdopen(fd, "wb") as f:
        f.write(response.content)

    return path


def transcribe_audio(file_path: str) -> str:
    with open(file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            file=audio_file,
            model="gpt-4o-transcribe"
        )
    return transcript.text


def main():
    print("Downloading recording...")
    audio_path = download_recording(RECORDING_URL)

    print("Transcribing audio...")
    transcript_text = transcribe_audio(audio_path)

    print("Saving to Google Sheets...")
    save_daily_transcription(transcript_text)

    print("Transcription complete.")


if __name__ == "__main__":
    main()
