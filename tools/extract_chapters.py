"""Extract per-chapter text from the book PDF into extracted/chNN-<slug>.txt.

Chapters are derived from the PDF's top-level bookmarks whose title starts
with "Chapter". Each output file is plain text with page markers
"===== [PDF page N] =====" so summaries can reference source pages.

Usage: py tools/extract_chapters.py   (run from anywhere; needs PyMuPDF)
"""
from pathlib import Path
import re
import sys

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / "Windows Kernel Programming, 2nd Edition (Pavel Yosifovich).pdf"
OUT_DIR = ROOT / "extracted"


def slugify(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()[:40]


def main() -> None:
    doc = pymupdf.open(PDF_PATH)
    chapters = []  # (num, title, start_page_1based)
    for level, title, page in doc.get_toc():
        if level != 1:
            continue
        m = re.match(r"Chapter\s+(\d+)\s*[:.]?\s*(.*)", title, re.IGNORECASE)
        if m:
            chapters.append((int(m.group(1)), m.group(2).strip() or title, page))
    if not chapters:
        sys.exit("No 'Chapter N' level-1 bookmarks found in the PDF")

    OUT_DIR.mkdir(exist_ok=True)
    for i, (num, title, start) in enumerate(chapters):
        end = chapters[i + 1][2] - 1 if i + 1 < len(chapters) else doc.page_count
        parts = [f"CHAPTER {num}: {title} (PDF pages {start}-{end})\n"]
        chars = 0
        for p in range(start, end + 1):  # 1-based, inclusive
            text = doc[p - 1].get_text("text").strip("\n")
            parts.append(f"\n===== [PDF page {p}] =====\n{text}\n")
            chars += len(text)
        out = OUT_DIR / f"ch{num:02d}-{slugify(title)}.txt"
        out.write_text("".join(parts), encoding="utf-8")
        print(f"{out.name}: pages {start}-{end}, {chars:,} chars")
    print(f"total chapters: {len(chapters)}")


if __name__ == "__main__":
    main()
