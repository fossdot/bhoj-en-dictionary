#!/usr/bin/env python3
"""Extract plain text from the Bhojpuri Wikipedia XML dump.

Input:  data/raw/bhwiki/bhwiki-latest-pages-articles.xml.bz2
Output: data/corpus/mono/bhwiki.txt   (paragraphs, blank line between articles)
        data/corpus/mono/bhwiki-titles.txt

License of the text: CC BY-SA 4.0 (Wikipedia).

Usage:
    python3 pipeline/extract_bhwiki.py
"""

import bz2
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DUMP = ROOT / "data" / "raw" / "bhwiki" / "bhwiki-latest-pages-articles.xml.bz2"
OUT_DIR = ROOT / "data" / "corpus" / "mono"

NS = "{http://www.mediawiki.org/xml/export-0.11/}"  # fixed up at runtime


def strip_wikitext(text: str) -> str:
    # kill tables and refs wholesale
    text = re.sub(r"\{\|.*?\|\}", "", text, flags=re.S)
    text = re.sub(r"<ref[^>/]*/>", "", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    # nested templates, innermost-out
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    # files/images/categories (with possible nested [[..]] in captions)
    text = re.sub(r"\[\[(?:File|Image|चित्र|श्रेणी|Category)[^\[\]]*(?:\[\[[^\]]*\]\][^\[\]]*)*\]\]", "", text, flags=re.I)
    # links: keep display text
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[https?://\S+\s+([^\]]+)\]", r"\1", text)
    text = re.sub(r"\[https?://\S+\]", "", text)
    # markup leftovers
    text = text.replace("'''", "").replace("''", "")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"^=+\s*.*?\s*=+\s*$", "", text, flags=re.M)  # headings
    text = re.sub(r"^[*#:;]+\s*", "", text, flags=re.M)  # list markers
    text = re.sub(r"&[a-z]+;", " ", text)
    # collapse whitespace, keep paragraph structure
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if len(ln) > 30)


DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n_articles = n_lines = 0
    titles = []

    with bz2.open(DUMP, "rb") as f, (OUT_DIR / "bhwiki.txt").open("w") as out:
        ns = None
        for event, elem in ET.iterparse(f, events=("end",)):
            if ns is None and "}" in elem.tag:
                ns = elem.tag.split("}")[0] + "}"
            if elem.tag != f"{ns}page":
                continue
            page_ns = elem.findtext(f"{ns}ns")
            title = elem.findtext(f"{ns}title") or ""
            text_el = elem.find(f"{ns}revision/{ns}text")
            raw = text_el.text if text_el is not None else None
            elem.clear()
            if page_ns != "0" or not raw or raw.lstrip()[:9].upper().startswith("#REDIRECT") or raw.lstrip().startswith("#अनुप्रेषित"):
                continue
            text = strip_wikitext(raw)
            # keep only lines that are mostly Devanagari (drop English/table debris)
            keep = [
                ln for ln in text.splitlines()
                if len(DEVANAGARI_RE.findall(ln)) > len(ln) * 0.4
            ]
            if not keep:
                continue
            titles.append(title)
            out.write("\n".join(keep) + "\n\n")
            n_articles += 1
            n_lines += len(keep)
            if n_articles % 2000 == 0:
                print(f"  {n_articles} articles …", file=sys.stderr)

    (OUT_DIR / "bhwiki-titles.txt").write_text("\n".join(titles) + "\n")
    print(f"{n_articles} articles, {n_lines} text lines → {OUT_DIR}/bhwiki.txt", file=sys.stderr)


if __name__ == "__main__":
    main()
