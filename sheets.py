from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
import os

# The ID of your Google Sheet (you'll set this in Render as an environment variable)
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

# The OAuth scope needed to edit Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Load service account credentials from service_account.json
creds = Credentials.from_service_account_file("service_account.json", scopes=SCOPES)

def append_to_sheet(full_name, email, phone, testing_center, color_code):
    """Append a new row of user data to Google Sheets."""
    try:
        service = build("sheets", "v4", credentials=creds)
        sheet = service.spreadsheets()

        new_row = [[full_name, email, phone, testing_center, color_code]]

        sheet.values().append(
            spreadsheetId=SHEET_ID,
            range="Sheet1!A:E",  # First 5 columns
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": new_row}
        ).execute()

    except Exception as e:
        print("Error writing to Google Sheet:", e)
        raise
