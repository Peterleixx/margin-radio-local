"""Local production profiles. Only a server-side reference travels with a job."""

import json
import os
import re
import secrets
import tempfile
from urllib.parse import urlsplit

from . import library
from .library import database

PRESETS = {
    "openai": {
        "label": "OpenAI",
        "protocol": "speech",
        "endpoint": "https://api.openai.com/v1/audio/speech",
        "model": "gpt-4o-mini-tts",
        "voice": "coral",
        "voices": ["coral", "alloy", "marin", "cedar"],
    },
    "openrouter": {
        "label": "OpenRouter",
        "protocol": "speech",
        "endpoint": "https://openrouter.ai/api/v1/audio/speech",
        "model": "",
        "voice": "",
        "voices": [],
    },
    "elevenlabs": {
        "label": "ElevenLabs",
        "protocol": "elevenlabs",
        "endpoint": "https://api.elevenlabs.io/v1/text-to-speech",
        "model": "eleven_multilingual_v2",
        "voice": "",
        "voices": [],
    },
    "compatible": {
        "label": "自定义 Speech API",
        "protocol": "speech",
        "endpoint": "",
        "model": "",
        "voice": "",
        "voices": [],
    },
}


def active(db):
    row = db.execute("""SELECT p.body FROM tts_profiles p JOIN preferences s
                        ON s.name='active_profile' AND s.value=p.id""").fetchone()
    return json.loads(row[0]) if row else None


def public(config):
    return {
        **{
            key: config[key]
            for key in ("id", "name", "provider", "endpoint", "model", "voice")
        },
        "has_key": bool(config["secret"]),
    }


def listing(db):
    current = active(db)
    return {
        "active": current["id"] if current else None,
        "presets": PRESETS,
        "profiles": [
            public(json.loads(row[0]))
            for row in db.execute("SELECT body FROM tts_profiles ORDER BY rowid")
        ],
    }


def checked_text(body, key, limit):
    value = body.get(key)
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("请检查字段：" + key)
    return value.strip()


def validate_endpoint(provider, endpoint):
    if provider != "compatible":
        if endpoint != PRESETS[provider]["endpoint"]:
            raise ValueError("请使用该供应商的官方端点，其他地址请选择自定义接口。")
        return
    url = urlsplit(endpoint)
    local_http = url.scheme == "http" and url.hostname in (
        "127.0.0.1",
        "localhost",
        "::1",
    )
    if (
        not url.hostname
        or not (url.scheme == "https" or local_http)
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or not url.path.strip("/")
        or any(c.isspace() or c == "\\" for c in endpoint)
    ):
        raise ValueError(
            "请填写完整的 HTTPS 合成端点；本机服务也可使用 HTTP。地址不能带凭据或查询参数。"
        )
    _ = url.port


def store_key(token, previous):
    folder = library.DATA / "credentials"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    ref = (
        previous
        if previous and re.fullmatch("[0-9a-f]{32}", previous)
        else secrets.token_hex(16)
    )
    with tempfile.NamedTemporaryFile(mode="w", dir=folder, delete=False) as f:
        f.write(token)
    os.replace(f.name, folder / ref)
    return ref


def resolve_key(p):
    # Key rotation also repairs a retry of an earlier job at the same destination.
    with database() as db:
        row = db.execute(
            "SELECT body FROM tts_profiles WHERE id=?", (p["id"],)
        ).fetchone()
    current = json.loads(row[0]) if row else None
    if current and (current["provider"], current["endpoint"]) == (
        p["provider"],
        p["endpoint"],
    ):
        p = current
    ref = p["secret"]
    if not ref:
        return ""
    if not re.fullmatch("[0-9a-f]{32}", ref):
        raise ValueError("配音凭据配置无效")
    try:
        return (library.DATA / "credentials" / ref).read_text()
    except FileNotFoundError:
        raise ValueError("本机找不到此配置的密钥，请在制作设置中重新填写。") from None


def save_active(body):
    if not isinstance(body, dict):
        raise ValueError("配置格式无效")  # noqa: TRY004 - invalid JSON values are input errors
    provider = body.get("provider")
    if not isinstance(provider, str) or provider not in PRESETS:
        raise ValueError("请选择支持的接口类型")
    fields = {
        k: checked_text(body, k, n)
        for k, n in (("name", 80), ("endpoint", 1200), ("model", 200), ("voice", 200))
    }
    validate_endpoint(provider, fields["endpoint"])
    if provider == "elevenlabs" and not re.fullmatch(
        r"[a-zA-Z0-9_-]+", fields["voice"]
    ):
        raise ValueError("请填写 ElevenLabs 音色 ID。")
    token = body.get("token", "")
    if (
        not isinstance(token, str)
        or len(token) > 8192
        or (
            token
            and (
                not token.isascii()
                or not token.isprintable()
                or any(c.isspace() for c in token)
            )
        )
    ):
        raise ValueError("密钥格式无效")
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        ident = body.get("id")
        old = None
        if ident:
            if not isinstance(ident, str) or not re.fullmatch("[0-9a-f]{32}", ident):
                raise ValueError("配置 ID 无效")
            row = db.execute(
                "SELECT body FROM tts_profiles WHERE id=?", (ident,)
            ).fetchone()
            if row:
                old = json.loads(row[0])
            else:
                raise ValueError("找不到此配置")
        else:
            ident = secrets.token_hex(16)
        same = (
            old
            and old["provider"] == provider
            and old["endpoint"] == fields["endpoint"]
        )
        ref = old["secret"] if same else ""
        if token:
            ref = store_key(token, ref)
        elif not ref and provider != "compatible":
            raise ValueError("请为该供应商填写 API 密钥")
        elif not ref and old and not same and old["secret"]:
            raise ValueError("接口地址已改变，请填写新端点的密钥；免密服务请新建配置。")
        record = dict(fields, id=ident, provider=provider, secret=ref)
        db.execute(
            "INSERT OR REPLACE INTO tts_profiles VALUES (?,?)",
            (ident, json.dumps(record)),
        )
        db.execute(
            "INSERT OR REPLACE INTO preferences VALUES ('active_profile',?)", (ident,)
        )
        return listing(db)
