import os
import json
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build

# Spreadsheet ID comes from an environment variable
SPREADSHEET_ID = os.environ.get("GOOGLE_SHEET_ID")

SUBSCRIBERS_SHEET = "Subscribers"
TRANSCRIPTIONS_SHEET = "DailyTranscriptions"


def _get_sheets_service():
    """Create an authorized Google Sheets API client from env JSON."""
    json_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not json_str:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON environment variable is missing.")

    cred_info = json.loads(json_str)
    creds = service_account.Credentials.from_service_account_info(
        cred_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    service = build("sheets", "v4", credentials=creds)
    return service


def add_subscriber(full_name: str, email: str, cell_number: str, testing_center: str):
    """
    Append a subscriber row to the Subscribers sheet.
    Columns: full_name | email | cell_number | testing_center
    """
    if not SPREADSHEET_ID:
        raise ValueError("GOOGLE_SHEET_ID environment variable is missing.")

    service = _get_sheets_service()
    sheet = service.spreadsheets()
    row = [[full_name, email, cell_number, testing_center]]

    sheet.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SUBSCRIBERS_SHEET}!A:D",
        valueInputOption="USER_ENTERED",
        body={"values": row},
    ).execute()


def get_all_subscribers():
    """
    Return a list of subscriber dicts from the Subscribers sheet.
    Each dict: { 'full_name', 'email', 'cell_number', 'testing_center' }
    """
    if not SPREADSHEET_ID:
        raise ValueError("GOOGLE_SHEET_ID environment variable is missing.")

    service = _get_sheets_service()
    sheet = service.spreadsheets()

    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SUBSCRIBERS_SHEET}!A:D",
    ).execute()

    values = result.get("values", [])
    subscribers = []
    for row in values:
        # pad row to length 4
        while len(row) < 4:
            row.append("")
        subscribers.append(
            {
                "full_name": row[0],
                "email": row[1],
                "cell_number": row[2],
                "testing_center": row[3],
            }
        )
    return subscribers


def save_daily_transcription(transcription_text: str, date_str: str | None = None):
    """
    Append a transcription row to DailyTranscriptions.
    Columns: date (YYYY-MM-DD) | transcription_text
    """
    if not SPREADSHEET_ID:
        raise ValueError("GOOGLE_SHEET_ID environment variable is missing.")

    if not date_str:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")

    service = _get_sheets_service()
    sheet = service.spreadsheets()
    row = [[date_str, transcription_text]]

    sheet.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{TRANSCRIPTIONS_SHEET}!A:B",
        valueInputOption="USER_ENTERED",
        body={"values": row},
    ).execute()


def get_latest_transcription():
    """
    Return (date_str, transcription_text) for the last row in DailyTranscriptions,
    or (None, None) if there are no rows.
    """
    if not SPREADSHEET_ID:
        raise ValueError("GOOGLE_SHEET_ID environment variable is missing.")

    service = _get_sheets_service()
    sheet = service.spreadsheets()

    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{TRANSCRIPTIONS_SHEET}!A:B",
    ).execute()

    values = result.get("values", [])
    if not values:
        return None, None

    last = values[-1]
    while len(last) < 2:
        last.append("")

    return last[0], last[1]
