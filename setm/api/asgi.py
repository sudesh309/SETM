"""Optional FastAPI/ASGI adapter.

Same route table, served by uvicorn/gunicorn when you want multiple workers,
TLS, or to sit behind a corporate reverse proxy::

    pip install 'setm[server]'
    uvicorn setm.api.asgi:app --workers 4

Scaling note: the graph is held in memory per process, so multiple *workers*
need a shared backend and a read-mostly deployment. For a writable multi-user
setup, run one worker (threads handle concurrency fine) or put SETM behind the
``http`` backend pointing at a shared service.
"""

from __future__ import annotations

import os
from typing import Any

from ..config import Settings
from ..errors import DependencyMissing
from ..workspace import Workspace
from .routes import Request, dispatch
from .security import SECURITY_HEADERS, BodyError, check_host, content_length, guard
from .server import WEB_ROOT


def create_app(settings: Settings | None = None) -> Any:
    try:
        from fastapi import FastAPI, Response as FastAPIResponse
        from fastapi.requests import Request as FastAPIRequest
        from fastapi.staticfiles import StaticFiles
    except ImportError:
        raise DependencyMissing("fastapi", "server", "The ASGI adapter") from None

    settings = settings or Settings.load()
    workspace = Workspace.open(settings)
    app = FastAPI(title="SETM", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")

    def _finish(*, content: bytes, status: int, media_type: str, headers: dict[str, str]) -> Any:
        return FastAPIResponse(
            content=content,
            status_code=status,
            media_type=media_type,
            headers={**SECURITY_HEADERS, **headers},
        )

    @app.middleware("http")
    async def _handle(incoming: FastAPIRequest, call_next: Any) -> Any:
        path = incoming.url.path
        headers = {k.lower(): v for k, v in incoming.headers.items()}
        if not (path.startswith("/api/") or path == "/metrics"):
            denied = check_host(Request(method=incoming.method, path=path, headers=headers), settings)
            if denied is not None:
                return _finish(content=denied.rendered(), status=denied.status,
                               media_type=denied.content_type, headers={})
            response = await call_next(incoming)
            for key, value in SECURITY_HEADERS.items():
                response.headers.setdefault(key, value)
            return response

        try:
            content_length(headers.get("content-length"))
        except BodyError as exc:
            refused = exc.response()
            return _finish(content=refused.rendered(), status=refused.status,
                           media_type=refused.content_type, headers={})
        raw = await incoming.body()
        body: Any = None
        if raw:
            import json

            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                body = raw.decode("utf-8", "replace")

        request = Request(
            method=incoming.method,
            path=path,
            query={k: incoming.query_params.getlist(k) for k in incoming.query_params},
            body=body,
            headers=headers,
        )
        response = guard(request, settings) or dispatch(workspace, request)
        return _finish(content=response.rendered(), status=response.status,
                       media_type=response.content_type, headers=response.headers)

    if WEB_ROOT.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_ROOT), html=True), name="web")

    app.state.workspace = workspace
    app.state.settings = settings
    return app


app = None
if os.environ.get("SETM_ASGI_AUTOLOAD", "1") not in ("0", "false"):  # pragma: no cover
    try:
        app = create_app()
    except Exception:
        # Import-time failures must not hide the real error from `uvicorn --factory`.
        app = None
