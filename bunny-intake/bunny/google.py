"""Google Sheets + Drive via one OAuth login (credentials.json -> token.json)."""
import io

from . import config

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",  # only files this app creates
]


def _creds():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if config.TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(config.TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not config.CREDENTIALS_FILE.exists():
                raise SystemExit(
                    f"Missing {config.CREDENTIALS_FILE.name}. See README > Google login."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(config.CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        config.TOKEN_FILE.write_text(creds.to_json())
    return creds


def sheets():
    from googleapiclient.discovery import build
    return build("sheets", "v4", credentials=_creds()).spreadsheets()


def drive():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=_creds())


# ---------- Sheet helpers ----------

def read_roster():
    """Return (header, rows) where rows are dicts with an extra '_row' (1-based sheet row)."""
    rng = f"'{config.SHEET_TAB}'!A1:Z1000"
    values = sheets().values().get(spreadsheetId=config.SHEET_ID, range=rng).execute().get("values", [])
    if not values:
        return [], []
    header = values[0]
    rows = []
    for i, v in enumerate(values[1:], start=2):
        v = v + [""] * (len(header) - len(v))
        d = dict(zip(header, v))
        d["_row"] = i
        if d.get(config.COL_NAME, "").strip():
            rows.append(d)
    return header, rows


def col_letter(header, name):
    idx = header.index(name)
    s = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def write_cell(header, row, col_name, value):
    cell = f"'{config.SHEET_TAB}'!{col_letter(header, col_name)}{row}"
    sheets().values().update(
        spreadsheetId=config.SHEET_ID, range=cell, valueInputOption="RAW",
        body={"values": [[value]]},
    ).execute()


def append_row(header, record: dict):
    row = [record.get(h, "") for h in header]
    sheets().values().append(
        spreadsheetId=config.SHEET_ID, range=f"'{config.SHEET_TAB}'!A1",
        valueInputOption="RAW", insertDataOption="INSERT_ROWS", body={"values": [row]},
    ).execute()


# ---------- Drive helpers ----------

def ensure_folder(name=None):
    name = name or config.DRIVE_FOLDER
    d = drive()
    q = (f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' "
         "and trashed = false")
    hits = d.files().list(q=q, fields="files(id,name)").execute().get("files", [])
    if hits:
        return hits[0]["id"]
    f = d.files().create(body={"name": name, "mimeType": "application/vnd.google-apps.folder"},
                         fields="id").execute()
    return f["id"]


def upload_text_as_doc(folder_id, title, text):
    """Upload plain text, converted to a Google Doc (NotebookLM reads Docs from Drive)."""
    from googleapiclient.http import MediaIoBaseUpload
    media = MediaIoBaseUpload(io.BytesIO(text.encode("utf-8")), mimetype="text/plain", resumable=False)
    body = {"name": title, "parents": [folder_id], "mimeType": "application/vnd.google-apps.document"}
    return drive().files().create(body=body, media_body=media, fields="id,webViewLink").execute()
