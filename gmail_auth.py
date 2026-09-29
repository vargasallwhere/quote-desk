"""Gmail login. On Replit it reads the GMAIL_TOKEN_JSON secret; on Sara's Mac it falls back to her saved token file."""
import json, os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.compose", "https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_FILE = os.path.expanduser("~/Claude_projects/gmail_token.json")


def get_gmail_service():
    raw = os.environ.get("GMAIL_TOKEN_JSON")
    if raw:
        creds = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
    elif os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    else:
        raise FileNotFoundError("Gmail is not connected. Set the GMAIL_TOKEN_JSON secret.")
    if not creds.valid:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)
