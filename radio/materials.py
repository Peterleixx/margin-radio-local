"""Read a specifically chosen attachment into text with source locations."""

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader


def captions(text):
    blocks = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.splitlines()
        for i, line in enumerate(lines):
            if "-->" in line:
                words = re.sub("<[^>]+>", "", " ".join(lines[i + 1 :])).strip()
                if words:
                    blocks.append(f"[{line.split('-->')[0].strip()}] {words}")
                break
    return "\n".join(blocks)


def read_file(filename):
    path = Path(filename).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise ValueError("请指定用户选定文件的绝对路径")
    ext = path.suffix.lower()
    if (
        ext in (".pdf", ".docx", ".srt", ".vtt", ".txt", ".md", ".markdown")
        and path.stat().st_size > 32 * 1024 * 1024
    ):
        raise ValueError("附件超过 32 MiB，请选取需要的章节或节选。")
    if ext == ".pdf":
        return "\n\n".join(
            f"[第 {i} 页]\n{t}"
            for i, p in enumerate(PdfReader(path).pages, 1)
            if (t := p.extract_text()) and t.strip()
        )
    if ext == ".docx":
        with zipfile.ZipFile(path) as z:
            if z.getinfo("word/document.xml").file_size > 16 * 1024 * 1024:
                raise ValueError("文档正文过大，请选取节选。")
            doc = ElementTree.fromstring(z.read("word/document.xml"))
        return "\n".join(
            "".join(t.text or "" for t in p.findall(".//{*}t"))
            for p in doc.findall(".//{*}p")
        )
    if ext in (".srt", ".vtt"):
        return captions(path.read_text(encoding="utf-8-sig"))
    if ext in (".txt", ".md", ".markdown"):
        return path.read_text(encoding="utf-8-sig")
    if ext in (".mp4", ".m4v", ".mkv", ".webm", ".mov", ".mp3", ".m4a", ".wav", ".ogg"):
        for suffix in (".vtt", ".srt"):
            sub = path.with_suffix(suffix)
            if sub.is_file() and (text := read_file(str(sub))):
                return text
        raise ValueError("未找到同名字幕。请提供同名 SRT、VTT 或逐字稿。")
    raise ValueError("请提供 TXT、Markdown、可提取文字的 PDF、DOCX、字幕或音视频文件。")
