"""Single-process entrypoint for hosting on a single-port PaaS (e.g. Hugging Face Spaces).

Serves the built React SPA at ``/`` and the unchanged API at ``/api`` from one container,
so the browser uses one origin and no reverse proxy is required. The API's own lifespan
(schema setup, seeding, monitoring loops) is run explicitly because Starlette does not
run the lifespan of mounted sub-applications.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .main import app as api_app


class SPAStaticFiles(StaticFiles):
    """Static files with client-side routing fallback to index.html."""

    async def get_response(self, path, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404:
            return await super().get_response("index.html", scope)
        return response


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with api_app.router.lifespan_context(api_app):
        yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/api", api_app)

_static = Path(os.environ.get("SPA_DIR", "/app/static"))
if _static.is_dir():
    app.mount("/", SPAStaticFiles(directory=_static, html=True), name="spa")


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; connect-src 'self'; img-src 'self' data:; "
            "frame-ancestors 'none'; base-uri 'self'",
        )
    return response
