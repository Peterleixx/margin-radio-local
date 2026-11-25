"""Loopback-only listening shelf."""

import hashlib
import json
import re

import uvicorn
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from . import library, profiles

WEB = library.ROOT / "web"


def index(request):
    return FileResponse(WEB / "library.html")


def catalog(request):
    with library.database() as db:
        rows = db.execute(
            "SELECT id,published FROM jobs WHERE state='ready' ORDER BY id"
        )
        revision = hashlib.sha256(
            repr([tuple(row) for row in rows]).encode()
        ).hexdigest()
    tag = '"' + revision + '"'
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers={"ETag": tag})
    return JSONResponse({"episodes": library.list_episodes()}, headers={"ETag": tag})


async def local_json(request):
    if (
        request.headers.get("origin") != str(request.base_url).rstrip("/")
        or request.headers.get("content-type", "").split(";")[0] != "application/json"
    ):
        raise HTTPException(403)
    raw = bytearray()
    async for piece in request.stream():
        raw.extend(piece)
        if len(raw) > 32768:
            raise HTTPException(413)
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise HTTPException(400, "无效的 JSON") from None


async def settings(request):
    if request.method == "GET":
        with library.database() as db:
            return JSONResponse(profiles.listing(db))
    body = await local_json(request)
    try:
        return JSONResponse(await run_in_threadpool(profiles.save_active, body))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def compose(request):
    body = await local_json(request)
    try:
        draft = library.Draft.model_validate(body)
    except ValueError:
        return JSONResponse({"error": "请检查标题和听稿长度。"}, status_code=400)
    try:
        saved = await run_in_threadpool(library.save, draft)
        return JSONResponse(await run_in_threadpool(library.render, saved["draft_id"]))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


def status(request):
    try:
        return JSONResponse(library.status(request.path_params["ident"]))
    except ValueError:
        return Response(status_code=404)


def track(request):
    ident = request.path_params["ident"]
    if re.fullmatch("[a-f0-9]{32}", ident):
        path = library.DATA / "audio" / (ident + ".mp3")
        if path.is_file():
            return FileResponse(path, media_type="audio/mpeg")
    return Response(status_code=404)


def resource(request):
    name = request.path_params["name"]
    if name in ("library.js", "library.css", "settings.js"):
        return FileResponse(WEB / name)
    return Response(status_code=404)


app = Starlette(
    routes=[
        Route("/", index),
        Route("/api/episodes", catalog),
        Route("/api/tts-profiles", settings, methods=["GET", "POST"]),
        Route("/api/drafts", compose, methods=["POST"]),
        Route("/api/jobs/{ident}", status),
        Route("/audio/{ident}.mp3", track),
        Route("/{name}", resource),
    ]
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])


@app.middleware("http")
async def headers(request, call_next):
    if request.headers.get("sec-fetch-site") == "cross-site":
        return Response(status_code=403)
    response = await call_next(request)
    response.headers.update(
        {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        }
    )
    return response


if __name__ == "__main__":
    uvicorn.run(
        app, host="127.0.0.1", port=library.PORT, proxy_headers=False, access_log=False
    )
