"""Extract reading-order paragraphs from a PDF."""

from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf

_BULLET = re.compile(r"^\s*([\u2022\u25cf\u25aa\-\*\u00b7]|\(?\d+[\.\)]|[a-z]\))\s+")
_SENTENCE_END = re.compile(r"[.!?:;\"\u201d\)]\s*$")


@dataclass
class Paragraph:
    page: int
    index: int
    text: str

    @property
    def key(self) -> str:
        return f"{self.page}:{self.index}"


def _join_lines(lines: list[str]) -> str:
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not out:
            out = line
        elif out.endswith("-") and not out.endswith("--"):
            out = out[:-1] + line
        else:
            out = out + " " + line
    return re.sub(r"\s{2,}", " ", out).strip()


def _is_noise(text: str) -> bool:
    if len(text) < 2:
        return True
    letters = sum(c.isalpha() for c in text)
    return letters < max(2, len(text) * 0.3)


def _mergeable(prev: str, nxt: str) -> bool:
    """A block that ends mid-sentence continues into the next one."""
    if _SENTENCE_END.search(prev):
        return False
    if _BULLET.match(nxt):
        return False
    return bool(nxt) and (nxt[0].islower() or nxt[0] in ",;")


def extract_paragraphs(path: str, first_page: int = 1, last_page: int | None = None) -> list[Paragraph]:
    doc = pymupdf.open(path)
    try:
        last = doc.page_count if last_page is None else min(last_page, doc.page_count)
        paragraphs: list[Paragraph] = []
        for page_no in range(max(1, first_page), last + 1):
            page = doc[page_no - 1]
            blocks = [b for b in page.get_text("blocks") if b[6] == 0]
            blocks.sort(key=lambda b: (round(b[1], 1), b[0]))
            texts: list[str] = []
            for block in blocks:
                text = _join_lines(block[4].splitlines())
                if not text or _is_noise(text):
                    continue
                if texts and _mergeable(texts[-1], text):
                    texts[-1] = texts[-1] + " " + text
                else:
                    texts.append(text)
            for i, text in enumerate(texts):
                paragraphs.append(Paragraph(page=page_no, index=i, text=text))
        return paragraphs
    finally:
        doc.close()


def page_count(path: str) -> int:
    doc = pymupdf.open(path)
    try:
        return doc.page_count
    finally:
        doc.close()
