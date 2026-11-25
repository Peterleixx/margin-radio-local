"""Source materials, drafts and local narration jobs."""

import fcntl
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv("MARGIN_RADIO_LOCAL_DATA", ROOT / "data")).expanduser().resolve()
PORT = int(os.getenv("MARGIN_RADIO_LOCAL_PORT", "18766"))
if not 1 <= PORT <= 65535:
    raise ValueError("端口须在 1 到 65535 之间")
BASE = f"http://127.0.0.1:{PORT}"
Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)
]
Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1800)
]


class Chapter(BaseModel):
    title: Title
    text: Text
    sources: list[Title] = Field(default_factory=list, max_length=12)


class Material(BaseModel):
    kind: Literal["chat", "document", "video", "article"]
    label: Title
    locator: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    language: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
    ]
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800000)
    ]


class Reading(BaseModel):
    material_id: Annotated[str, StringConstraints(pattern="^[a-f0-9]{32}$")]
    chinese: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800000)
    ]


class Production(BaseModel):
    mode: Literal["podcast", "audiobook"]
    summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=12000)
    ]
    readings: list[Reading] = Field(min_length=1, max_length=48)


class Draft(BaseModel):
    title: Title
    chapters: list[Chapter] = Field(min_length=1, max_length=48)

    production: Production | None = None


def now():
    return datetime.now(UTC).isoformat(timespec="seconds")


@contextmanager
def database():
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(DATA / "radio.sqlite3", timeout=20)
    db.row_factory = sqlite3.Row
    try:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS tts_profiles (id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS preferences (name TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS job_configs (job TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS materials (id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, draft TEXT NOT NULL, voice TEXT NOT NULL,
          state TEXT NOT NULL, progress INTEGER NOT NULL, info TEXT, error TEXT, published TEXT);
        """)
        with db:
            yield db
    finally:
        db.close()


def fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def save(draft):
    body = draft.model_dump_json(exclude_none=True)
    ident = fingerprint(body)
    with database() as db:
        if draft.production:
            for r in draft.production.readings:
                if not db.execute(
                    "SELECT 1 FROM materials WHERE id=?", (r.material_id,)
                ).fetchone():
                    raise ValueError("找不到来源材料：" + r.material_id)
        db.execute("INSERT OR IGNORE INTO drafts VALUES (?,?)", (ident, body))
    return {"draft_id": ident, "title": draft.title, "chapters": len(draft.chapters)}


def get_draft(ident):
    with database() as db:
        row = db.execute("SELECT body FROM drafts WHERE id=?", (ident,)).fetchone()
    if not row:
        raise ValueError("找不到该稿件版本")
    return json.loads(row[0])


def lock_file(ident):
    path = DATA / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    handle = (path / (ident + ".lock")).open("a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def register_material(material):
    body = material.model_dump_json()
    ident = fingerprint(body)
    with database() as db:
        db.execute("INSERT OR IGNORE INTO materials VALUES (?,?)", (ident, body))
    return {
        "material_id": ident,
        "label": material.label,
        "characters": len(material.text),
    }


def get_material(ident):
    with database() as db:
        row = db.execute("SELECT body FROM materials WHERE id=?", (ident,)).fetchone()
    if not row:
        raise ValueError("找不到来源材料")
    return json.loads(row[0])


def render(draft_id):
    from .profiles import active

    get_draft(draft_id)
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        config = active(db)
        if not config:
            raise ValueError("请先在本机节目库的「配音设置」中保存一个配置。")
        identity = [draft_id] + [
            config[k] for k in ("id", "provider", "endpoint", "model", "voice")
        ]
        ident = fingerprint(json.dumps(identity))
        db.execute(
            "INSERT OR IGNORE INTO job_configs VALUES (?,?)",
            (ident, json.dumps(config)),
        )
        db.execute(
            "INSERT OR IGNORE INTO jobs(id,draft,voice,state,progress) VALUES(?,?,?,'queued',0)",
            (ident, draft_id, config["voice"]),
        )
    guard = lock_file(ident)
    if guard is None:
        return status(ident)
    with guard, database() as db:
        row = db.execute("SELECT state FROM jobs WHERE id=?", (ident,)).fetchone()
        if row[0] != "ready" or not (DATA / "audio" / (ident + ".mp3")).is_file():
            db.execute(
                "UPDATE jobs SET state='rendering', progress=0, error=NULL WHERE id=?",
                (ident,),
            )
            db.commit()
            try:
                worker = subprocess.Popen(
                    [sys.executable, "-m", "radio.worker", ident],
                    cwd=ROOT,
                    pass_fds=[guard.fileno()],
                    start_new_session=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                Thread(target=worker.wait, daemon=True).start()
            except OSError:
                db.execute(
                    "UPDATE jobs SET state='failed',error='无法启动配音进程' WHERE id=?",
                    (ident,),
                )
    return status(ident)


def links(ident):
    return {"url": f"{BASE}/?episode={ident}", "audio_url": f"{BASE}/audio/{ident}.mp3"}


def status(ident):
    with database() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (ident,)).fetchone()
        if row is None:
            raise ValueError("找不到该节目")
        if row["state"] == "rendering":
            guard = lock_file(ident)
            if guard is not None:
                with guard:
                    db.execute(
                        "UPDATE jobs SET state='failed',error='配音中断，请重新提交同一听稿' WHERE id=? AND state='rendering'",
                        (ident,),
                    )
                    db.commit()
                    row = db.execute(
                        "SELECT * FROM jobs WHERE id=?", (ident,)
                    ).fetchone()
        draft = get_draft(row["draft"])
        result = {
            "episode_id": ident,
            "draft_id": row["draft"],
            "title": draft["title"],
            "voice": row["voice"],
            "status": row["state"],
            "completed_chapters": row["progress"],
            "total_chapters": len(draft["chapters"]),
        }
        if row["state"] == "ready":
            result.update(links(ident))
        elif row["error"]:
            result["error"] = row["error"]
        return result


def list_episodes():
    with database() as db:
        rows = db.execute(
            "SELECT id,info FROM jobs WHERE state='ready' ORDER BY published DESC,rowid DESC"
        ).fetchall()
    return [
        dict(
            json.loads(row["info"]),
            id=row["id"],
            episode_id=row["id"],
            src=f"/audio/{row['id']}.mp3",
            **links(row["id"]),
        )
        for row in rows
        if (DATA / "audio" / (row["id"] + ".mp3")).is_file()
    ]


def work(ident):
    from .speech import SpeechError, synthesize

    try:
        with database() as db:
            row = db.execute(
                "SELECT jobs.draft, job_configs.body FROM jobs JOIN job_configs ON jobs.id=job_configs.job WHERE jobs.id=?",
                (ident,),
            ).fetchone()
        draft = get_draft(row["draft"])
        config = json.loads(row["body"])
        out = DATA / "audio"
        out.mkdir(exist_ok=True)

        def progress(count):
            with database() as db:
                db.execute("UPDATE jobs SET progress=? WHERE id=?", (count, ident))

        with tempfile.TemporaryDirectory(dir=out) as tmp:
            dest = Path(tmp) / "episode.mp3"
            info = synthesize(draft["chapters"], config, DATA / "tts", dest, progress)
            info.update(title=draft["title"], draft_id=row["draft"])
            if production := draft.get("production"):
                info.update(mode=production["mode"], summary=production["summary"])
                info["readings"] = []
                for reading in production["readings"]:
                    material = get_material(reading["material_id"])
                    info["readings"].append(
                        dict(
                            reading,
                            **{
                                key: material[key]
                                for key in ("label", "kind", "locator", "language")
                            },
                        )
                    )
            dest.replace(out / (ident + ".mp3"))
            with database() as db:
                db.execute(
                    "UPDATE jobs SET state='ready', info=?, published=?, error=NULL WHERE id=?",
                    (json.dumps(info, ensure_ascii=False), now(), ident),
                )
    except Exception as exc:  # noqa: BLE001 - a detached worker must persist a terminal job state
        message = (
            str(exc)
            if isinstance(exc, SpeechError)
            else "制作失败，请检查配音配置、网络和可用磁盘空间后重试。"
        )
        with database() as db:
            db.execute(
                "UPDATE jobs SET state='failed',error=? WHERE id=?", (message, ident)
            )
