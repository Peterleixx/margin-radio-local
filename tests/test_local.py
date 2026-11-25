"""Verify a complete recording through a local test speech endpoint."""

import concurrent.futures
import io
import json
import math
import os
import secrets
import struct
import tempfile
import time
import unittest
import wave
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

import httpx
from starlette.testclient import TestClient

from radio import library, materials, profiles, speech, web


@contextmanager
def speech_service():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setparams((1, 2, 24000, 0, "NONE", ""))
        wav.writeframes(
            b"".join(
                struct.pack("<h", int(8000 * math.sin(i / 9))) for i in range(36000)
            )
        )
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.headers.get("Authorization"), body))
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(stream.getvalue())))
            self.end_headers()
            self.wfile.write(stream.getvalue())

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/speech", received
        finally:
            server.shutdown()
            thread.join()


class LocalStudioTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data = Path(folder.name) / "library"
        for context in (
            patch.object(library, "DATA", self.data),
            patch.dict(os.environ, MARGIN_RADIO_LOCAL_DATA=str(self.data)),
        ):
            context.start()
            self.addCleanup(context.stop)
        self.client = TestClient(web.app, base_url=library.BASE)

    def test_local_recording(self):
        service = speech_service()
        self.addCleanup(service.__exit__, None, None, None)
        endpoint, received = service.__enter__()
        token = secrets.token_urlsafe()
        profile = {
            "name": "旁白",
            "provider": "compatible",
            "model": "reader",
            "voice": "narrator",
            "endpoint": endpoint,
            "token": token,
        }
        listing = profiles.save_active(profile)
        self.assertNotIn(token, json.dumps(listing))
        material = library.register_material(
            library.Material(
                kind="article",
                label="读书笔记",
                locator="第一段",
                language="中文",
                text="清晨的窗外传来鸟鸣。",
            )
        )
        saved = library.save(
            library.Draft(
                title="试播",
                chapters=[
                    library.Chapter(title="清晨", text="清晨的窗外传来鸟鸣。"),
                    library.Chapter(title="傍晚", text="傍晚的街道逐渐安静。"),
                ],
                production=library.Production(
                    mode="podcast",
                    summary="一天的声音。",
                    readings=[
                        library.Reading(
                            material_id=material["material_id"],
                            chinese="清晨的窗外传来鸟鸣。",
                        )
                    ],
                ),
            )
        )
        with concurrent.futures.ThreadPoolExecutor(3) as pool:
            renders = list(pool.map(library.render, [saved["draft_id"]] * 3))
        self.assertEqual(len({job["episode_id"] for job in renders}), 1)
        ident = renders[0]["episode_id"]
        deadline = time.monotonic() + 60
        while (state := library.status(ident))["status"] in (
            "queued",
            "rendering",
        ) and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertEqual(state["status"], "ready", state)
        self.assertEqual(library.render(saved["draft_id"])["status"], "ready")
        self.assertEqual(len(received), 2)
        for auth, params in received:
            self.assertEqual(auth, "Bearer " + token)
            self.assertEqual(params["model"], "reader")
            self.assertEqual(params["voice"], "narrator")
        (episode,) = self.client.get("/api/episodes").json()["episodes"]
        self.assertEqual(episode["readings"][0]["label"], "读书笔记")
        self.assertGreater(episode["chapters"][1]["start"], 0)
        audio = self.client.get(episode["src"], headers={"Range": "bytes=0-127"})
        self.assertEqual(audio.status_code, 206)
        self.assertEqual(len(audio.content), 128)
        self.assertEqual(state["audio_url"], library.BASE + episode["src"])

        profiles.save_active(
            dict(profile, id=listing["active"], voice="second", token="")
        )
        other = library.render(saved["draft_id"])
        self.assertNotEqual(other["episode_id"], ident)
        for _ in range(300):
            other = library.status(other["episode_id"])
            if other["status"] in ("failed", "ready"):
                break
            time.sleep(0.1)
        self.assertEqual(other["status"], "ready", other)
        self.assertEqual(received[-1][1]["voice"], "second")

    def test_profile_boundaries(self):
        path = "/api/tts-profiles"
        origin = {"Origin": library.BASE}
        self.assertIsNone(self.client.get(path).json()["active"])
        token = secrets.token_urlsafe()
        body = {
            "provider": "compatible",
            "endpoint": "http://localhost/speech",
            "model": "m",
            "voice": "v",
            "name": "n",
            "token": token,
        }
        self.assertEqual(self.client.post(path, json=body).status_code, 403)
        result = self.client.post(path, json=body, headers=origin)
        self.assertEqual(result.status_code, 200)
        self.assertNotIn(token, result.text)
        ident = result.json()["active"]
        with library.database() as db:
            first = profiles.active(db)
        self.assertEqual(
            (self.data / "credentials" / first["secret"]).stat().st_mode & 0o777, 0o600
        )
        changed = dict(body, id=ident, token="", endpoint="https://example.org/speech")
        self.assertEqual(
            self.client.post(path, json=changed, headers=origin).status_code, 400
        )
        rotated = secrets.token_urlsafe()
        profiles.save_active(dict(body, id=ident, token=rotated))
        self.assertEqual(profiles.resolve_key(first), rotated)
        self.assertNotIn(rotated, self.client.get(path).text)
        for url in (
            "http://example.org/speech",
            "https://example.org/speech?t=x",
            "https://user@example.org/speech",
        ):
            with self.assertRaises(ValueError):
                profiles.validate_endpoint("compatible", url)

    def test_provider_requests(self):
        for name in ("openai", "openrouter", "elevenlabs"):
            config = dict(
                profiles.PRESETS[name],
                provider=name,
                model="chosen-model",
                voice="chosen-voice",
            )

            def upstream(request, name=name):
                body = json.loads(request.content)
                if name == "elevenlabs":
                    self.assertTrue(request.url.path.endswith("/chosen-voice"))
                    self.assertEqual(request.headers.get("xi-api-key"), "fixture")
                    self.assertEqual(body, {"text": "听稿", "model_id": "chosen-model"})
                else:
                    self.assertEqual(request.headers["Authorization"], "Bearer fixture")
                    self.assertEqual(
                        body,
                        {
                            "input": "听稿",
                            "model": "chosen-model",
                            "voice": "chosen-voice",
                            "response_format": "mp3",
                        },
                    )
                return httpx.Response(
                    307, headers={"Location": "https://example.org/redirect"}
                )

            with (
                httpx.Client(transport=httpx.MockTransport(upstream)) as client,
                self.assertRaisesRegex(speech.SpeechError, "307"),
            ):
                speech.render_http(client, config, "听稿", "fixture")

    def test_web_boundaries(self):
        self.assertEqual(
            self.client.get("/", headers={"Host": "outside.invalid"}).status_code, 400
        )
        self.assertEqual(self.client.post("/api/drafts", json={}).status_code, 403)
        self.assertEqual(
            self.client.post(
                "/api/drafts", json={}, headers={"Origin": library.BASE}
            ).status_code,
            400,
        )
        self.assertEqual(self.client.get("/data/radio.sqlite3").status_code, 404)

    def test_video_uses_local_subtitles(self):
        path = self.data.parent / "clip.mp4"
        path.touch()
        with self.assertRaisesRegex(ValueError, "字幕"):
            materials.read_file(str(path))
        path.with_suffix(".vtt").write_text(
            "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n中文听稿。"
        )
        self.assertIn("中文听稿。", materials.read_file(str(path)))


if __name__ == "__main__":
    unittest.main()
