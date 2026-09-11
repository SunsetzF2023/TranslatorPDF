"""Command line mode: translate a PDF straight to a bilingual file."""

from __future__ import annotations

import argparse
import os
import sys

from .exporter import export_html, export_pdf
from .pdf_reader import extract_paragraphs
from .translator import Translator, available_providers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Translate an English PDF into a bilingual file.")
    parser.add_argument("pdf")
    parser.add_argument("-o", "--output", help="output file (.pdf or .html)")
    parser.add_argument("--provider", default="google", choices=list(available_providers()))
    parser.add_argument("--target", default="zh-CN")
    parser.add_argument("--first-page", type=int, default=1)
    parser.add_argument("--last-page", type=int)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args(argv)

    paragraphs = extract_paragraphs(args.pdf, args.first_page, args.last_page)
    if not paragraphs:
        print("No extractable text (scanned PDF?).", file=sys.stderr)
        return 1

    output = args.output or os.path.splitext(args.pdf)[0] + "_bilingual.pdf"
    translator = Translator(
        provider=args.provider, target=args.target, workers=args.workers, use_cache=not args.no_cache
    )
    done = 0

    def on_result(_pos: int, _text: str, error: str | None) -> None:
        nonlocal done
        done += 1
        print(f"\r{done}/{len(paragraphs)}" + (f"  error: {error}" if error else ""), end="", flush=True)

    translations = translator.translate_many([p.text for p in paragraphs], on_result=on_result)
    print()

    pairs = [(p.page, p.text, t) for p, t in zip(paragraphs, translations) if t]
    if not pairs:
        print("Translation failed for every paragraph.", file=sys.stderr)
        return 1
    if output.lower().endswith(".html"):
        export_html(output, os.path.basename(args.pdf), pairs)
    else:
        export_pdf(output, os.path.basename(args.pdf), pairs, target=args.target)
    print(f"Wrote {output}")
    return 0
