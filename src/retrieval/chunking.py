"""Split knowledge markdown into embeddable chunks."""

from __future__ import annotations

from dataclasses import dataclass

# Soft max chars per chunk (OpenAI embeddings handle much more; keep citations tight)
DEFAULT_MAX_CHUNK_CHARS = 700


@dataclass(frozen=True)
class TextChunk:
    index: int
    text: str


def chunk_markdown(text: str, *, max_chars: int = DEFAULT_MAX_CHUNK_CHARS) -> list[TextChunk]:
    """
    Chunk on ## headings first, then split long sections by paragraphs.
    """
    cleaned = text.strip()
    if not cleaned:
        return []

    sections = _split_sections(cleaned)
    raw_parts: list[str] = []
    for section in sections:
        if len(section) <= max_chars:
            raw_parts.append(section)
        else:
            raw_parts.extend(_split_long(section, max_chars=max_chars))

    chunks: list[TextChunk] = []
    for i, part in enumerate(raw_parts):
        piece = part.strip()
        if piece:
            chunks.append(TextChunk(index=i, text=piece))
    return chunks


def _split_sections(text: str) -> list[str]:
    lines = text.splitlines()
    sections: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("## ") and current:
            sections.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current).strip())
    return [s for s in sections if s]


def _split_long(section: str, *, max_chars: int) -> list[str]:
    paras = [p.strip() for p in section.split("\n\n") if p.strip()]
    if not paras:
        return _hard_split(section, max_chars=max_chars)

    out: list[str] = []
    buf = ""
    for para in paras:
        candidate = f"{buf}\n\n{para}".strip() if buf else para
        if len(candidate) <= max_chars:
            buf = candidate
            continue
        if buf:
            out.append(buf)
        if len(para) <= max_chars:
            buf = para
        else:
            out.extend(_hard_split(para, max_chars=max_chars))
            buf = ""
    if buf:
        out.append(buf)
    return out


def _hard_split(text: str, *, max_chars: int) -> list[str]:
    parts: list[str] = []
    start = 0
    while start < len(text):
        parts.append(text[start : start + max_chars].strip())
        start += max_chars
    return [p for p in parts if p]
