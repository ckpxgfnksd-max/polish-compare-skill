#!/usr/bin/env python3
"""Prepare a source manifest from a local PDF with a text layer."""

import argparse
from bisect import bisect_right
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ROMAN_END = r"(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})"
ROMAN_NUMBER = rf"(?=[ivxlcdm])m{{0,3}}(?:cm|cd|d?c{{0,3}}){ROMAN_END}"
# Unprefixed Roman folios typically number front matter. A word like "mix"
# also spells a number above this range (MIX = 1009).
ROMAN_FRONT = rf"(?=[ivxlc])c{{0,3}}{ROMAN_END}"
REFERENCES = re.compile(
    rf"(?:(?:\d+(?:\.\d+)*|{ROMAN_NUMBER})[.)]?\s+)?"
    r"(?:references(?:\s+(?:cited|and\s+notes))?|bibliography|"
    r"works\s+cited|literature\s+cited|reference\s+list)\s*[:.]?",
    re.IGNORECASE,
)
FOLIO = re.compile(
    rf"(?:(?:page|p\.)\s*(?:\d+|{ROMAN_NUMBER})|\d+|{ROMAN_FRONT})"
    r"(?:\s*(?:of|/)\s*\d+)?",
    re.IGNORECASE,
)
BAD_TEXT = re.compile(r"[\x00-\x08\x0b\x0d-\x1f\x7f-\x9f\ufffd]")
END = re.compile(r"""(?:[.!?]+["'”’»)\]]*(?=\s|$)|[。！？]+[」』）”’]*)""")
SHORT_FORM = re.compile(
    r"\b(?:al|approx|ave|dept|dr|e\.g|ed|eds|eq|eqs|etc|fig|figs|"
    r"i\.e|inc|jr|mr|mrs|ms|no|nos|p|pp|prof|sec|st|vol|vs|[a-z])\.$",
    re.IGNORECASE,
)


def extract(pdf):
    executable = shutil.which("pdftotext")
    if not executable:
        raise ValueError("Poppler pdftotext is missing from PATH. Install Poppler or add its bin directory to PATH.")
    result = subprocess.run(
        [executable, "-layout", "-enc", "UTF-8", "-eol", "unix", "-", "-"],
        input=pdf, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    message = result.stderr.decode("utf-8", errors="replace").strip()
    if result.returncode:
        raise ValueError(f"pdftotext exited {result.returncode}. {message}")
    if message:
        print(f"pdftotext reported: {message}", file=sys.stderr)
    pages = result.stdout.decode("utf-8", errors="replace").split("\f")
    # The final form feed closes the last physical page, including an empty one.
    if pages[-1] == "" and len(pages) > 1:
        pages.pop()
    missing = []
    for number, page in enumerate(pages, start=1):
        corrupt = BAD_TEXT.search(page)
        if corrupt:
            missing.append(f"{number} (unexpected U+{ord(corrupt[0]):04X})")
            continue
        content = " ".join(line.strip() for line in page.split("\n")
                           if not FOLIO.fullmatch(line.strip()))
        if not any(ch.isalpha() for ch in content):
            missing.append(str(number))
        elif sum(ch.isalpha() for ch in content) < 40:
            print(f"PDF page {number} has little extractable text. Check for scanned content.", file=sys.stderr)
    if missing:
        raise ValueError(
            f"No usable text layer on PDF page(s) {', '.join(missing)}. Inspect those pages, "
            "then OCR a copy or transcribe the source. See references/pdf-intake.md."
        )
    return pages


def blocks(page):
    """Keep standalone folios and bibliography headings apart from surrounding prose."""
    block = []
    for number, line in enumerate(page.split("\n"), start=1):
        text = line.strip()
        standalone = REFERENCES.fullmatch(text) or FOLIO.fullmatch(text)
        if (not text or standalone) and block:
            yield block
            block = []
        if standalone:
            yield [(number, text)]
        elif text:
            block.append((number, text))
    if block:
        yield block


def sentences(text):
    start = 0
    for match in END.finditer(text):
        if text[match.start()] == ".":
            context = text[max(start, match.start() - 24):match.start() + 1]
            if SHORT_FORM.search(context):
                continue
        yield start, match.end()
        start = match.end()
        while start < len(text) and text[start].isspace():
            start += 1
    if start < len(text):
        yield start, len(text)


def make_rows(pages):
    rows = []
    paragraph = 0
    in_references = False
    for page_number, page in enumerate(pages, start=1):
        for block in blocks(page):
            paragraph += 1
            text = " ".join(line for _, line in block)
            if REFERENCES.fullmatch(text):
                in_references = True
            fixed = in_references or bool(FOLIO.fullmatch(text))
            line_starts = []
            offset = 0
            for _, line in block:
                line_starts.append(offset)
                offset += len(line) + 1
            for start, end in ([(0, len(text))] if fixed else sentences(text)):
                first = block[bisect_right(line_starts, start) - 1][0]
                last = block[bisect_right(line_starts, end - 1) - 1][0]
                location = f"line {first}" if first == last else f"lines {first}–{last}"
                rows.append({
                    "id": f"s{len(rows) + 1:03d}",
                    "paragraph": f"p{paragraph:02d}",
                    "locator": f"PDF p. {page_number}, extracted {location}",
                    "text": text[start:end],
                    "kind": "fixed" if fixed else "prose",
                })
    return rows


def write_new(path, manifest):
    # Publish a fully written file. A competing writer or an earlier edition wins.
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        temporary = Path(directory) / "source.json"
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.link(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", metavar="INPUT.pdf", type=Path)
    parser.add_argument("output", metavar="SOURCE.json", type=Path)
    parser.add_argument("--title", default="Manuscript comparison", help="display title")
    args = parser.parse_args()
    try:
        pdf = args.pdf.read_bytes()
        pages = extract(pdf)
        manifest = {"title": args.title, "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
                    "rows": make_rows(pages), "figures": []}
        write_new(args.output, manifest)
    except FileExistsError:
        parser.exit(1, f"Error: output already exists: {args.output}\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")
    print(f"Preliminary manifest: {len(pages)} pages, {len(manifest['rows'])} rows. "
          "Check every rendered page, reading order, references, and figures before packing.")


if __name__ == "__main__":
    main()
