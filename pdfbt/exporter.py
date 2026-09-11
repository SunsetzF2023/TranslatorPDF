"""Write the bilingual result to HTML or PDF."""

from __future__ import annotations

import html
import re
from typing import Sequence

import pymupdf

PAGE_SIZE = pymupdf.paper_rect("a4")
MARGIN = 50
GAP = 6
EN_FONT = "helv"
ZH_FONT = "china-s"  # PyMuPDF built-in Simplified Chinese font
ZH_FONT_TRADITIONAL = "china-t"
ZH_FONTS = {"zh-CN": ZH_FONT, "zh-TW": ZH_FONT_TRADITIONAL}

HTML_TEMPLATE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>{title}</title>
<style>
 body {{ font-family: -apple-system, "Segoe UI", "Noto Sans CJK SC", sans-serif;
        margin: 0 auto; max-width: 1200px; padding: 24px; line-height: 1.7; color: #1f2328; }}
 h1 {{ font-size: 20px; }}
 .page-label {{ margin: 28px 0 8px; font-size: 12px; color: #888; border-bottom: 1px solid #eee; }}
 .row {{ display: flex; gap: 24px; padding: 10px 0; border-bottom: 1px solid #f2f2f2; }}
 .col {{ flex: 1; }}
 .src {{ color: #444; }}
 .dst {{ color: #0b4f9e; }}
 @media print {{ .row {{ break-inside: avoid; }} }}
</style></head><body>
<h1>{title}</h1>
{rows}
</body></html>
"""


def export_html(path: str, title: str, pairs: Sequence[tuple[int, str, str]]) -> None:
    rows: list[str] = []
    last_page = None
    for page, source, translated in pairs:
        if page != last_page:
            rows.append(f'<div class="page-label">第 {page} 页 / Page {page}</div>')
            last_page = page
        rows.append(
            '<div class="row">'
            f'<div class="col src">{html.escape(source)}</div>'
            f'<div class="col dst">{html.escape(translated)}</div>'
            "</div>"
        )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(HTML_TEMPLATE.format(title=html.escape(title), rows="\n".join(rows)))


def _split_half(text: str) -> tuple[str, str]:
    pieces = re.split(r"(?<=[.!?。！？])\s+", text)
    if len(pieces) > 1:
        mid = len(pieces) // 2
        return " ".join(pieces[:mid]), " ".join(pieces[mid:])
    mid = len(text) // 2
    cut = text.rfind(" ", 0, mid) or mid
    return text[:cut], text[cut:]


class _PdfWriter:
    def __init__(self, zh_font: str):
        self.doc = pymupdf.open()
        self.zh_font = zh_font
        self.page = self.doc.new_page(width=PAGE_SIZE.width, height=PAGE_SIZE.height)
        self.y = MARGIN

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=PAGE_SIZE.width, height=PAGE_SIZE.height)
        self.y = MARGIN

    def write(self, text: str, font: str, size: float, color=(0, 0, 0)) -> None:
        text = text.strip()
        if not text:
            return
        if font == self.zh_font and text.isascii():
            font = EN_FONT  # the CJK fonts letter-space Latin text badly
        bottom = PAGE_SIZE.height - MARGIN
        for _ in range(3):
            rect = pymupdf.Rect(MARGIN, self.y, PAGE_SIZE.width - MARGIN, bottom)
            if rect.height > size * 2:
                leftover = self.page.insert_textbox(
                    rect, text, fontname=font, fontsize=size, color=color, lineheight=1.35
                )
                if leftover >= 0:
                    self.y = bottom - leftover + GAP
                    return
            if self.y > MARGIN:
                self._new_page()
                continue
            head, tail = _split_half(text)
            if not tail.strip():
                return
            self.write(head, font, size, color)
            self.write(tail, font, size, color)
            return

    def space(self, amount: float) -> None:
        self.y += amount

    def save(self, path: str) -> None:
        self.doc.save(path, garbage=3, deflate=True)
        self.doc.close()


def export_pdf(
    path: str,
    title: str,
    pairs: Sequence[tuple[int, str, str]],
    target: str = "zh-CN",
    font_size: float = 10.5,
) -> None:
    writer = _PdfWriter(ZH_FONTS.get(target, ZH_FONT))
    writer.write(title, writer.zh_font, font_size + 4)
    writer.space(6)
    last_page = None
    for page, source, translated in pairs:
        if page != last_page:
            writer.space(6)
            writer.write(
                f"—— 第 {page} 页 / Page {page} ——",
                writer.zh_font,
                font_size - 1.5,
                color=(0.55, 0.55, 0.55),
            )
            last_page = page
        writer.write(source, EN_FONT, font_size, color=(0.15, 0.15, 0.15))
        writer.write(translated, writer.zh_font, font_size, color=(0.04, 0.24, 0.55))
        writer.space(5)
    writer.save(path)
