"""HTTP narration protocols. All adapters return the same mono 24 kHz PCM."""

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

from .profiles import PRESETS, resolve_key

RATE = 24000


class SpeechError(ValueError):
    pass


def speech_request(config, text, token):
    headers = {"Authorization": "Bearer " + token} if token else {}
    return (
        config["endpoint"],
        headers,
        {
            "model": config["model"],
            "voice": config["voice"],
            "input": text,
            "response_format": "mp3",
        },
    )


def elevenlabs_request(config, text, token):
    return (
        config["endpoint"] + "/" + config["voice"],
        {"xi-api-key": token},
        {"model_id": config["model"], "text": text},
    )


REQUESTS = {"speech": speech_request, "elevenlabs": elevenlabs_request}


def render_http(client, config, text, token):
    builder = REQUESTS[PRESETS[config["provider"]]["protocol"]]
    url, headers, body = builder(config, text, token)
    try:
        with client.stream(
            "POST", url, headers=headers, json=body, follow_redirects=False
        ) as response:
            if response.status_code != 200:
                raise SpeechError(
                    f"配音接口返回 HTTP {response.status_code}，请核对端点、密钥、额度、模型和音色。"
                )
            data = bytearray()
            for part in response.iter_bytes():
                data.extend(part)
                if len(data) > 32 * 1024 * 1024:
                    raise SpeechError("上游返回的单章音频超过大小限制")
    except httpx.HTTPError:
        raise SpeechError("无法连接配音接口，请检查地址与网络。") from None
    decoded = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-protocol_whitelist",
            "pipe",
            "-i",
            "pipe:0",
            "-vn",
            "-t",
            "301",
            "-f",
            "s16le",
            "-ar",
            "24000",
            "-ac",
            "1",
            "pipe:1",
        ],
        input=data,
        check=False,
        capture_output=True,
        timeout=75,
    )
    if decoded.returncode or not decoded.stdout:
        raise SpeechError("配音接口没有返回可解码的音频")
    if len(decoded.stdout) > 300 * RATE * 2:
        raise SpeechError("上游返回的单段音频过长，请检查接口。")
    return decoded.stdout


def run(command):
    try:
        subprocess.run(
            command,
            check=True,
            timeout=300,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise SpeechError(f"找不到 {command[0]}，请运行 bin/setup。") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise SpeechError(f"{command[0]} 处理失败，请检查 FFmpeg 安装。") from exc


def passages(text, limit=400):
    while len(text) > limit:
        stops = list(re.finditer(r"[。！？；.!?\n，,、 ]", text[:limit]))
        end = stops[-1].end() if stops else limit
        yield text[:end]
        text = text[end:]
    if text:
        yield text


def synthesize(chapters, config, cache, destination, progress):
    key = resolve_key(config)
    identity = [config[k] for k in ("id", "provider", "endpoint", "model", "voice")]
    cache.mkdir(exist_ok=True)
    timeline = []
    with (
        httpx.Client(timeout=120, trust_env=False) as client,
        tempfile.TemporaryDirectory(dir=cache) as temp,
    ):
        folder = Path(temp)
        segment = folder / "chapter.pcm"
        recording = folder / "recording.pcm"
        with recording.open("wb") as output:
            for index, chapter in enumerate(chapters):
                if index:
                    output.write(bytes(RATE // 3 * 2))
                timeline.append(
                    dict(chapter, start=round(output.tell() / (RATE * 2), 3))
                )
                for passage in passages(chapter["text"]):
                    digest = hashlib.sha256(
                        json.dumps([identity, RATE, passage]).encode()
                    ).hexdigest()
                    clip = cache / (digest + ".pcm")
                    if not clip.exists():
                        segment.write_bytes(render_http(client, config, passage, key))
                        segment.replace(clip)
                    with clip.open("rb") as piece:
                        shutil.copyfileobj(piece, output)
                progress(index + 1)
            duration = output.tell() / (RATE * 2)
        run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-f",
                "s16le",
                "-ar",
                str(RATE),
                "-ac",
                "1",
                "-i",
                str(recording),
                "-c:a",
                "libmp3lame",
                "-b:a",
                "96k",
                str(destination),
            ]
        )
    return {
        "voice": config["voice"],
        "model": config["model"],
        "provider": config["provider"],
        "profile_name": config["name"],
        "duration": round(duration, 3),
        "chapters": timeline,
    }
