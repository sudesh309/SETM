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
from .routes import Request, dispatch, require_token
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

    @app.middleware("http")
    async def _handle(incoming: FastAPIRequest, call_next: Any) -> Any:
        path = incoming.url.path
        if not (path.startswith("/api/") or path == "/metrics"):
            return await call_next(incoming)

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
            headers={k.lower(): v for k, v in incoming.headers.items()},
        )
        denied = require_token(request, settings.api_token)
        response = denied or dispatch(workspace, request)
        return FastAPIResponse(
            content=response.rendered(),
            status_code=response.status,
            media_type=response.content_type,
            headers=response.headers,
        )

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
