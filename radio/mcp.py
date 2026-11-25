"""Margin Radio local stdio server."""

import asyncio
from typing import Literal

from mcp.server.fastmcp import FastMCP

from . import library, materials

server = FastMCP("margin-radio")


@server.tool()
def import_material(
    kind: Literal["chat", "document", "video", "article"],
    label: str,
    locator: str,
    language: str,
    text: str | None = None,
    file_path: str | None = None,
) -> dict:
    """Import the chosen chat excerpt, fetched article body, transcript or local attachment. Supply either text or an absolute file_path. Local video uses a sibling VTT/SRT."""
    if (text is None) == (file_path is None):
        raise ValueError("提供正文或本机附件路径，二选一")
    if file_path is not None:
        text = materials.read_file(file_path)
    return library.register_material(
        library.Material(
            kind=kind, label=label, locator=locator, language=language, text=text
        )
    )


@server.tool()
def read_material(material_id: str, offset: int = 0, limit: int = 10000) -> dict:
    """Read the imported source in pages. Continue at next_offset until null."""
    m = library.get_material(material_id)
    text = m.pop("text")
    if offset < 0 or not 1 <= limit <= 30000:
        raise ValueError("offset ≥ 0，limit 在 1 到 30000 之间")
    return dict(
        m,
        text=text[offset : offset + limit],
        next_offset=offset + limit if offset + limit < len(text) else None,
    )


@server.tool()
def get_narration_settings() -> dict:
    """Read the selected provider, model and voice. Set up credentials in the local web UI."""
    from .profiles import active, public

    with library.database() as db:
        config = active(db)
        return (
            public(config)
            if config
            else {"configured": False, "settings_url": library.BASE + "/#settings"}
        )


@server.tool()
def save_draft(
    title: str,
    chapters: list[library.Chapter],
    production: library.Production | None = None,
) -> dict:
    """Save an immutable spoken script. Each chapter has title, text and optional source labels. For source-based programs include production mode, Chinese summary and translated readings keyed by material_id. For podcasts, use natural spoken Chinese for the intended audience, keeping customary terminology in any language and enough context to understand key figures. Identical input reuses the same version."""
    return library.save(
        library.Draft(title=title, chapters=chapters, production=production)
    )


@server.tool()
def get_draft(draft_id: str) -> dict:
    """Read a saved script, chapter texts and sources for revision."""
    return library.get_draft(draft_id)


@server.tool()
def render_episode(draft_id: str) -> dict:
    """Generate one narration per draft and selected voice profile on this computer. Repeat the same request to reuse or retry."""
    return library.render(draft_id)


@server.tool()
async def get_episode(episode_id: str, wait_seconds: int = 0) -> dict:
    """Check status and playback URLs. Optionally wait up to 25 seconds for narration."""
    loop = asyncio.get_running_loop()
    end = loop.time() + max(0, min(25, wait_seconds))
    while True:
        result = library.status(episode_id)
        if result["status"] not in ("queued", "rendering") or loop.time() >= end:
            return result
        await asyncio.sleep(min(1, end - loop.time()))


@server.tool()
def list_episodes() -> list[dict]:
    """List finished episodes and local playback URLs."""
    return library.list_episodes()


if __name__ == "__main__":
    server.run(transport="stdio")
