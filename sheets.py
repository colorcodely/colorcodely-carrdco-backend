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
    """Internal helper to create an authorized Google Sheets API client."""
    json_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not json_str:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON environment variable is missing.")

    cred_info = json.loads(json_str)
    creds = service_account.Credentials.from_service_account_info(
        cred_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=creds)


# --- PUBLIC WRAPPER (app.py imports this) ---
def get_sheets_service():
    """Expose the underlying Sheets service for app.py."""
    return _get_sheets_service()


# --- PUBLIC WRAPPER (app.py expects this name) ---
def append_row_to_sheet(sheet_name: str, row_values: list):
    """
    Generic row append function used by app.py.
    This allows app.py to push any row to any sheet.
    """
    if not SPREADSHEET_ID:
        raise ValueError("GOOGLE_SHEET_ID environment variable is missing.")

    service = _get_sheets_service()
    sheet = service.spreadsheets()

    sheet.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{sheet_name}!A:Z",
        valueInputOption="USER_ENTERED",
        body={"values": [row_values]},
    ).execute()


# ---------------------------------------------------------------------
#             SUBSCRIBER MANAGEMENT FUNCTIONS
# ---------------------------------------------------------------------

def add_subscriber(full_name: str, email: str, cell_number: str, testing_center: str):
    """
    Append a subscriber row to the Subscribers sheet.
    Columns: full_name | email | cell_number | testing_center
    """
    append_row_to_sheet(
        SUBSCRIBERS_SHEET,
        [full_name, email, cell_number, testing_center],
    )


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

    values = result.get("values", []) or []
    subscribers = []

    for row in values:
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


# ---------------------------------------------------------------------
#             DAILY TRANSCRIPTION FUNCTIONS
# ---------------------------------------------------------------------

def save_daily_transcription(transcription_text: str, date_str: str | None = None):
    """
    Append a transcription row to DailyTranscriptions.
    Columns: date (YYYY-MM-DD) | tran
