import base64
import json
import os
import re
from io import BytesIO
from typing import Any, List, Optional

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
except Exception:
    service_account = None
    build = None
    MediaIoBaseDownload = None
    MediaIoBaseUpload = None

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]
_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()
_SA_B64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_B64", "").strip()
_PREFIX = os.getenv("WARZONE_DRIVE_DATA_PREFIX", "warzone_data").strip() or "warzone_data"
_SERVICE = None
_SHEETS_SERVICE = None


def enabled() -> bool:
    return bool(_FOLDER_ID and _SA_B64 and service_account and build)


def sheets_enabled() -> bool:
    return bool(_SA_B64 and service_account and build)


def _credentials():
    if not _SA_B64 or not service_account:
        return None
    info = json.loads(base64.b64decode(_SA_B64).decode("utf-8"))
    return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)


def _service():
    global _SERVICE
    if _SERVICE is not None:
        return _SERVICE
    if not enabled():
        return None
    creds = _credentials()
    if not creds:
        return None
    _SERVICE = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _SERVICE


def _sheets_service():
    global _SHEETS_SERVICE
    if _SHEETS_SERVICE is not None:
        return _SHEETS_SERVICE
    if not sheets_enabled():
        return None
    creds = _credentials()
    if not creds:
        return None
    _SHEETS_SERVICE = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return _SHEETS_SERVICE


def extract_spreadsheet_id(value: str) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    # Full URL
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", text)
    if m:
        return m.group(1)
    # Bare spreadsheet id
    if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", text):
        return text
    return None


def extract_gid(value: str) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    m = re.search(r"[?&#]gid=([0-9]+)", text)
    return m.group(1) if m else None


def resolve_sheet_title(spreadsheet_id: str, preferred_name: str = "", gid: Optional[str] = None) -> Optional[str]:
    svc = _sheets_service()
    if not svc or not spreadsheet_id:
        return None
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,title))").execute()
    sheets = meta.get("sheets", []) or []
    if not sheets:
        return None
    preferred = str(preferred_name or "").strip()
    if preferred:
        for sh in sheets:
            title = (sh.get("properties") or {}).get("title") or ""
            if title == preferred:
                return title
    if gid is not None and str(gid).strip() != "":
        try:
            gid_int = int(str(gid))
        except Exception:
            gid_int = None
        if gid_int is not None:
            for sh in sheets:
                props = sh.get("properties") or {}
                if props.get("sheetId") == gid_int:
                    return props.get("title")
    return (sheets[0].get("properties") or {}).get("title")


def write_values(spreadsheet_id: str, sheet_title: str, values: List[List[Any]], clear_first: bool = True) -> bool:
    """Replace a worksheet with the given rows (including header)."""
    svc = _sheets_service()
    if not svc or not spreadsheet_id or not sheet_title:
        return False
    # Escape sheet title for A1 notation
    safe_title = str(sheet_title).replace("'", "''")
    rng = f"'{safe_title}'"
    if clear_first:
        svc.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=rng,
            body={},
        ).execute()
    body = {"values": values or [[]]}
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{rng}!A1",
        valueInputOption="RAW",
        body=body,
    ).execute()
    return True


def _file_name(key: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in key)
    return f"{_PREFIX}_{safe}.json"


def _find_file_id(key: str) -> Optional[str]:
    svc = _service()
    if not svc:
        return None
    name = _file_name(key)
    q = f"'{_FOLDER_ID}' in parents and name='{name}' and trashed=false"
    res = svc.files().list(q=q, spaces="drive", fields="files(id,name)", pageSize=1).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def load_json(key: str) -> Optional[Any]:
    svc = _service()
    if not svc:
        return None
    file_id = _find_file_id(key)
    if not file_id:
        return None
    request = svc.files().get_media(fileId=file_id)
    fh = BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    return json.loads(fh.read().decode("utf-8"))


def save_json(key: str, data: Any) -> bool:
    svc = _service()
    if not svc:
        return False
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    media = MediaIoBaseUpload(BytesIO(raw), mimetype="application/json", resumable=False)
    file_id = _find_file_id(key)
    if file_id:
        svc.files().update(fileId=file_id, media_body=media).execute()
    else:
        meta = {"name": _file_name(key), "parents": [_FOLDER_ID], "mimeType": "application/json"}
        svc.files().create(body=meta, media_body=media, fields="id").execute()
    return True


def upload_bytes(key: str, data: bytes, mime_type: str = "application/octet-stream") -> Optional[str]:
    svc = _service()
    if not svc:
        return None
    name = _file_name(key)
    # keep original extension if passed in key after .json replacement is undesirable
    if key.startswith("file_"):
        name = "".join(ch if ch.isalnum() or ch in "._-/" else "_" for ch in key).replace("/", "__")
    media = MediaIoBaseUpload(BytesIO(data), mimetype=mime_type, resumable=False)
    meta = {"name": name, "parents": [_FOLDER_ID]}
    created = svc.files().create(body=meta, media_body=media, fields="id").execute()
    return "gdrive:" + created["id"]


def download_bytes(ref: str) -> Optional[bytes]:
    svc = _service()
    if not svc or not str(ref).startswith("gdrive:"):
        return None
    file_id = str(ref).split(":", 1)[1]
    request = svc.files().get_media(fileId=file_id)
    fh = BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return fh.getvalue()


def delete_ref(ref: str) -> bool:
    svc = _service()
    if not svc or not str(ref).startswith("gdrive:"):
        return False
    try:
        svc.files().delete(fileId=str(ref).split(":", 1)[1]).execute()
        return True
    except Exception:
        return False


def _ensure_folder(name: str, parent_id: str) -> Optional[str]:
    svc = _service()
    if not svc:
        return None
    q = f"'{parent_id}' in parents and name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    res = svc.files().list(q=q, spaces="drive", fields="files(id,name)", pageSize=1).execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": name, "parents": [parent_id], "mimeType": "application/vnd.google-apps.folder"}
    created = svc.files().create(body=meta, fields="id").execute()
    return created.get("id")


def save_backup(name: str, data: Any) -> Optional[str]:
    svc = _service()
    if not svc:
        return None
    backup_folder = _ensure_folder("warzone_backups", _FOLDER_ID)
    if not backup_folder:
        return None
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    media = MediaIoBaseUpload(BytesIO(raw), mimetype="application/json", resumable=False)
    safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)
    meta = {"name": safe_name, "parents": [backup_folder], "mimeType": "application/json"}
    created = svc.files().create(body=meta, media_body=media, fields="id,webViewLink").execute()
    return created.get("id")
