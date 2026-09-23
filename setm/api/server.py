"""Standard-library HTTP server.

Chosen deliberately over a framework: SETM runs with nothing but CPython, which
matters when the tool has to be installed on a locked-down engineering
workstation. :mod:`setm.api.asgi` exposes the same routes through FastAPI for
deployments that want workers, TLS termination and the rest.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ..config import Settings
from ..kpi.telemetry import telemetry
from ..workspace import Workspace
from .routes import Request, Response, dispatch
from .security import MAX_BODY_BYTES, SECURITY_HEADERS, BodyError, check_host, content_length, guard  # noqa: F401

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"

logger = logging.getLogger("setm.server")


class _Handler(BaseHTTPRequestHandler):
    server_version = "SETM"
    protocol_version = "HTTP/1.1"

    workspace: Workspace
    settings: Settings

    # -- plumbing -----------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:  # quieter default logging
        logger.debug("%s - %s", self.address_string(), fmt % args)

    def _send(self, response: Response) -> None:
        payload = response.rendered()
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        for key, value in SECURITY_HEADERS.items():
            if key not in response.headers:
                self.send_header(key, value)
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD" and payload:
            self.wfile.write(payload)

    def _read_body(self) -> Any:
        """Read and decode the body. Raises BodyError for a malformed or oversize one."""
        length = content_length(self.headers.get("Content-Length"))
        if length == 0:
            return None
        raw = self.rfile.read(length)
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if content_type in ("application/json", ""):
            try:
                return json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
        return raw.decode("utf-8", "replace")

    def _build_request(self) -> Request:
        split = urlsplit(self.path)
        return Request(
            method=self.command,
            path=split.path,
            query=parse_qs(split.query),
            body=self._read_body(),
            headers={k.lower(): v for k, v in self.headers.items()},
        )

    # -- verbs --------------------------------------------------------------
    def _dispatch(self, *, static: bool = False) -> None:
        try:
            request = self._build_request()
        except BodyError as exc:
            # The body was not consumed, so the connection cannot be reused.
            self.close_connection = True
            self._send(exc.response())
            return
        if static and not (request.path.startswith("/api/") or request.path == "/metrics"):
            denied = check_host(request, self.settings)
            if denied is not None:
                self._send(denied)
            else:
                self._serve_static(request.path)
            return
        self._handle_api(request)

    def do_GET(self) -> None:
        self._dispatch(static=True)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        self._dispatch()

    def do_PATCH(self) -> None:
        self._dispatch()

    def do_PUT(self) -> None:
        self._dispatch()

    def do_DELETE(self) -> None:
        self._dispatch()

    def do_OPTIONS(self) -> None:
        self._send(
            Response(
                status=204,
                headers={
                    "Allow": "GET, POST, PATCH, PUT, DELETE, OPTIONS",
                    "Access-Control-Allow-Methods": "GET, POST, PATCH, PUT, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, X-SETM-Token, X-SETM-User",
                },
            )
        )

    def _handle_api(self, request: Request) -> None:
        denied = guard(request, self.settings)
        if denied is not None:
            self._send(denied)
            return
        self._send(dispatch(self.workspace, request))

    # -- static -------------------------------------------------------------
    def _serve_static(self, path: str) -> None:
        relative = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (WEB_ROOT / relative).resolve()
        try:
            target.relative_to(WEB_ROOT.resolve())
        except ValueError:
            self._send(Response(status=403, body={"error": {"message": "Forbidden"}}))
            return
        if not target.is_file():
            target = WEB_ROOT / "index.html"  # single-page app fallback
            if not target.is_file():
                self._send(Response(status=404, body={"error": {"message": f"Not found: {path}"}}))
                return
        content_type, _ = mimetypes.guess_type(str(target))
        telemetry.increment("http.static")
        self._send(
            Response(
                body=target.read_bytes(),
                content_type=content_type or "application/octet-stream",
                headers={"Cache-Control": "no-cache"},
            )
        )


def build_server(workspace: Workspace, settings: Settings) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (_Handler,), {"workspace": workspace, "settings": settings})
    server = ThreadingHTTPServer((settings.host, settings.port), handler)
    server.daemon_threads = True
    return server


def serve(workspace: Workspace, settings: Settings, *, block: bool = True) -> ThreadingHTTPServer:
    server = build_server(workspace, settings)
    host, port = server.server_address[0], server.server_address[1]
    url = f"http://{host}:{port}/"
    logger.info("SETM serving %s", url)
    print(f"\n  SETM is running at {url}")
    print(f"  project : {workspace.store.project.name}")
    print(f"  storage : {workspace.backend.scheme}:{workspace.backend.target}")
    print(f"  ontology: {workspace.ontology.id} v{workspace.ontology.version}")
    print(f"  graph   : {workspace.store.node_count} elements, {workspace.store.edge_count} relations")
    print("\n  Ctrl-C to stop\n")

    if settings.open_browser:
        threading.Timer(0.6, _open_browser, args=(url,)).start()

    if not block:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopping...")
    finally:
        server.shutdown()
        server.server_close()
        if workspace.store.dirty and workspace.backend.writable:
            try:
                workspace.save(message="shutdown flush")
                print("  Unsaved changes written to storage.")
            except Exception as exc:  # pragma: no cover
                print(f"  WARNING: could not flush changes: {exc}")
    return server


def _open_browser(url: str) -> None:  # pragma: no cover
    import webbrowser

    if os.environ.get("SETM_NO_BROWSER"):
        return
    try:
        webbrowser.open(url)
    except Exception:
        pass
