"""Shared Google authentication and HTTP plumbing for the Sheets/Drive backends.

Three credential routes, tried in order:

1. ``token`` option or ``SETM_GOOGLE_TOKEN`` -- a raw OAuth2 access token. No
   third-party package needed; handy for CI and for short-lived sessions
   (``gcloud auth print-access-token``).
2. ``credentials`` option or ``GOOGLE_APPLICATION_CREDENTIALS`` -- a service
   account JSON key. Needs ``google-auth`` (``pip install 'setm[google]'``).
3. Application Default Credentials, also via ``google-auth``.

Share the target sheet or folder with the service account's e-mail address,
exactly as you would with a colleague.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..errors import DependencyMissing, StorageError

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class GoogleClient:
    """Minimal authenticated JSON client for Google REST APIs."""

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        self.options = dict(options or {})
        self.timeout = float(self.options.get("timeout", 30))
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._credentials: Any = None

    # -- auth ---------------------------------------------------------------
    def access_token(self) -> str:
        with self._lock:
            static = self.options.get("token") or os.environ.get("SETM_GOOGLE_TOKEN")
            if static:
                return str(static)
            if self._token and time.time() < self._expires_at - 60:
                return self._token
            self._token, self._expires_at = self._mint_token()
            return self._token

    def _mint_token(self) -> tuple[str, float]:
        try:
            from google.auth.transport.requests import Request  # type: ignore
            from google.oauth2 import service_account  # type: ignore
        except ImportError:
            raise DependencyMissing("google-auth", "google", "Google Sheets/Drive access") from None

        key_file = self.options.get("credentials") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if key_file:
            credentials = service_account.Credentials.from_service_account_file(str(key_file), scopes=SCOPES)
        else:
            import google.auth  # type: ignore

            credentials, _ = google.auth.default(scopes=SCOPES)
        credentials.refresh(Request())
        self._credentials = credentials
        expiry = getattr(credentials, "expiry", None)
        expires_at = expiry.timestamp() if expiry else time.time() + 3000
        return str(credentials.token), expires_at

    # -- http ---------------------------------------------------------------
    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any = None,
        raw_body: bytes | None = None,
        content_type: str = "application/json",
    ) -> Any:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
        data = raw_body
        headers = {"Authorization": f"Bearer {self.access_token()}"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = content_type
        elif raw_body is not None:
            headers["Content-Type"] = content_type

        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload) if payload.strip() else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:600]
            raise StorageError(
                f"Google API {method} {url.split('?')[0]} failed with HTTP {exc.code}: {detail}",
                status_code=exc.code,
            ) from None
        except urllib.error.URLError as exc:
            raise StorageError(f"Could not reach the Google API: {exc.reason}") from None

    def health(self) -> dict[str, Any]:
        try:
            self.access_token()
            return {"status": "ok", "auth": "ready"}
        except DependencyMissing as exc:
            return {"status": "unconfigured", "error": exc.message}
        except StorageError as exc:
            return {"status": "error", "error": exc.message}
