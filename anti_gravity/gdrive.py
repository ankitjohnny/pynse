"""
Google Drive client for Project Anti-Gravity.

Handles OAuth2 authentication and read/write of the JSON state ledger stored
in Google Drive.  Falls back gracefully when google-api-python-client is not
installed — the rest of the pipeline still runs with local-only storage.

Setup
-----
1. Enable the Google Drive API in Google Cloud Console.
2. Create OAuth 2.0 credentials (Desktop app type) and download the JSON.
3. Place the file at ~/.anti_gravity/gdrive_credentials.json (or pass a path).
4. On first run the browser will open for consent; a token is cached afterwards.
"""
from __future__ import annotations

import json
import logging
import os
import pickle
from io import BytesIO
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
_DEFAULT_CREDENTIALS = os.path.expanduser("~/.anti_gravity/gdrive_credentials.json")
_DEFAULT_TOKEN       = os.path.expanduser("~/.anti_gravity/gdrive_token.pkl")

try:
    from googleapiclient.discovery import build as _build
    from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    _HAS_GDRIVE = True
except ImportError:
    _HAS_GDRIVE = False


class GoogleDriveClient:
    """Read/write JSON files in the authenticated user's Google Drive."""

    def __init__(
        self,
        credentials_path: str = _DEFAULT_CREDENTIALS,
        token_path: str = _DEFAULT_TOKEN,
    ):
        if not _HAS_GDRIVE:
            raise RuntimeError(
                "Google API libraries missing. Install with:\n"
                "  pip install google-api-python-client "
                "google-auth-httplib2 google-auth-oauthlib"
            )
        self._service = self._authenticate(credentials_path, token_path)
        self._file_id_cache: Dict[str, str] = {}

    # ── Authentication ────────────────────────────────────────────────────────

    @staticmethod
    def _authenticate(credentials_path: str, token_path: str):
        creds: Optional[Credentials] = None

        if os.path.exists(token_path):
            with open(token_path, "rb") as f:
                creds = pickle.load(f)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    credentials_path, _SCOPES
                )
                creds = flow.run_local_server(port=0)
            os.makedirs(os.path.dirname(token_path), exist_ok=True)
            with open(token_path, "wb") as f:
                pickle.dump(creds, f)

        return _build("drive", "v3", credentials=creds, cache_discovery=False)

    # ── File ID resolution ────────────────────────────────────────────────────

    def _find_file_id(self, filename: str) -> Optional[str]:
        if filename in self._file_id_cache:
            return self._file_id_cache[filename]
        resp = self._service.files().list(
            q=f"name='{filename}' and trashed=false",
            fields="files(id)",
            pageSize=1,
        ).execute()
        files = resp.get("files", [])
        if files:
            fid = files[0]["id"]
            self._file_id_cache[filename] = fid
            return fid
        return None

    # ── Public API ────────────────────────────────────────────────────────────

    def read_json(self, filename: str) -> Optional[Dict[str, Any]]:
        file_id = self._find_file_id(filename)
        if not file_id:
            logger.debug("No Drive file found: %s", filename)
            return None
        buf = BytesIO()
        downloader = MediaIoBaseDownload(
            buf, self._service.files().get_media(fileId=file_id)
        )
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return json.loads(buf.getvalue().decode("utf-8"))

    def write_json(self, filename: str, data: Dict[str, Any]) -> None:
        content = json.dumps(data, indent=2, default=str).encode("utf-8")
        media = MediaIoBaseUpload(BytesIO(content), mimetype="application/json")
        file_id = self._find_file_id(filename)
        if file_id:
            self._service.files().update(
                fileId=file_id, media_body=media
            ).execute()
            logger.debug("Updated Drive file: %s (%s)", filename, file_id)
        else:
            result = self._service.files().create(
                body={"name": filename},
                media_body=media,
                fields="id",
            ).execute()
            self._file_id_cache[filename] = result["id"]
            logger.info("Created Drive file: %s (%s)", filename, result["id"])
