import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build


def get_sheets_service():
    """
    Loads Google Sheets credentials from the environment variable
    GOOGLE_SERVICE_ACCOUNT_JSON and returns an authorized Sheets API service.
    """
    # Load the JSON from environment variables
    json_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

    if not json_str:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON environment variable is missing.")

    # Parse JSON into Python dict
    cred_info = json.loads(json_str)

    # Convert into Google credentials object
    creds = service_account.Credentials.from_service_account_info(
        cred_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )

    # Build the service
    service = build("sheets", "v4", credentials=creds)
    return service


def append_row_to_sheet(spreadsheet_id, row_values):
    """
    Appends a single row to the Google Sheet.
    spreadsheet_id: The ID of the Google Sheets document.
    row_values: A list of values representing a row.
    """
    service = get_sheets_service()
    sheet = service.spreadsheets()

    body = {
        "values": [row_values]
    }

    result = sheet.values().append(
        spreadsheetId=spreadsheet_id,
        range="Sheet1!A1",
        valueInputOption="USER_ENTERED",
        body=body
    ).execute()

    return result
