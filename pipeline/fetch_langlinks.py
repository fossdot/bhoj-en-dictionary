#!/usr/bin/env python3
"""Extract bho→en dictionary entries from Bhojpuri Wikipedia interlanguage links
and emit canonical JSONL entries (data/canonical/langlinks-bho.jsonl).

Joins two MySQL dumps from https://dumps.wikimedia.org/bhwiki/latest/ :
  page.sql      → page_id → title (namespace 0 only)
  langlinks.sql → ll_from page_id → English Wikipedia title (ll_lang = 'en')

The bho article title becomes the headword; the linked English article title
becomes the gloss. These are encyclopedic titles (mostly, but not all, proper
nouns) so pos is left empty. Wikipedia content is CC BY-SA 4.0.

Entries whose English title itself contains Devanagari (untranslated article
names — useless as English glosses) go to langlinks-bho-review.jsonl instead
and should NOT be imported.

Column order (verified against the CREATE TABLE statements in the dumps):
  page:      page_id, page_namespace, page_title, page_is_redirect, ...
  langlinks: ll_from, ll_lang, ll_title

Usage:
    python3 pipeline/fetch_langlinks.py
"""

import gzip
import json
import random
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE_SQL = ROOT / "data" / "raw" / "bhwiki" / "bhwiki-latest-page.sql.gz"
LL_SQL = ROOT / "data" / "raw" / "bhwiki" / "bhwiki-latest-langlinks.sql.gz"
OUT = ROOT / "data" / "canonical" / "langlinks-bho.jsonl"
REVIEW = ROOT / "data" / "canonical" / "langlinks-bho-review.jsonl"

# MySQL backslash escapes as they appear in mysqldump string literals.
UNESCAPE = {
    "0": "\0", "'": "'", '"': '"', "b": "\b", "n": "\n",
    "r": "\r", "t": "\t", "Z": "\x1a", "\\": "\\",
}

# Pure numbers / years / dates: digits (ASCII or Devanagari) + separators only.
NUMERIC_RE = re.compile(r"^[0-9०-९\s\-–/.,]+$")

EN_SKIP_PREFIXES = ("List of", "Category:", "Template:", "Wikipedia:")


def parse_tuples(values: str):
    """Yield rows (lists of str) from the VALUES part of an INSERT statement.

    Handles single-quoted strings with backslash escapes and '' doubling;
    unquoted tokens (numbers, NULL) come through as their literal text.
    """
    i, n = 0, len(values)
    while i < n:
        if values[i] != "(":
            i += 1
            continue
        i += 1
        row, buf = [], []
        while i < n:
            c = values[i]
            if c == "'":  # quoted string (may resume after '' doubling)
                i += 1
                while i < n:
                    c = values[i]
                    if c == "\\":
                        buf.append(UNESCAPE.get(values[i + 1], values[i + 1]))
                        i += 2
                    elif c == "'":
                        if i + 1 < n and values[i + 1] == "'":  # '' → literal '
                            buf.append("'")
                            i += 2
                        else:
                            i += 1
                            break
                    else:
                        buf.append(c)
                        i += 1
            elif c in ",)":
                row.append("".join(buf))
                buf = []
                i += 1
                if c == ")":
                    yield row
                    break
            else:
                buf.append(c)
                i += 1


def iter_rows(sql_gz: Path, table: str):
    """Yield value tuples from every INSERT INTO `table` VALUES ... statement."""
    prefix = f"INSERT INTO `{table}` VALUES "
    with gzip.open(sql_gz, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith(prefix):
                yield from parse_tuples(line[len(prefix):])


def detect_script(word: str) -> str:
    for ch in word:
        cp = ord(ch)
        if 0x11080 <= cp <= 0x110CF:
            return "Kthi"  # Kaithi
        if 0x0900 <= cp <= 0x097F:
            return "Deva"
    return "Latn"


def deva_ratio(title: str) -> float:
    chars = [c for c in title if not c.isspace()]
    if not chars:
        return 0.0
    return sum(0x0900 <= ord(c) <= 0x097F for c in chars) / len(chars)


def make_entry(bho: str, en: str) -> dict:
    return {
        "word": bho,
        "lang": "bho",
        "script": detect_script(bho),
        "translit": [],
        "phones": [],
        "tags": ["src:bhwiki-langlinks"],
        "senses": [{"pos": "", "gloss": en, "examples": []}],
        "source": "Bhojpuri Wikipedia interlanguage links",
        "source_url": "https://bh.wikipedia.org/wiki/"
        + urllib.parse.quote(bho.replace(" ", "_")),
        "license": "CC BY-SA 4.0",
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)

    # 1. page_id → title for namespace 0 (underscores become spaces).
    pages: dict[int, str] = {}
    total_pages = 0
    for row in iter_rows(PAGE_SQL, "page"):
        total_pages += 1
        if row[1] == "0":
            pages[int(row[0])] = row[2].replace("_", " ")
    print(f"page.sql: {total_pages} pages, {len(pages)} in namespace 0", file=sys.stderr)

    # 2+3. langlinks ll_lang='en', joined through the page map, then filtered.
    entries, review = [], []
    seen: set[str] = set()
    skip = {k: 0 for k in (
        "no-ns0-page", "not-devanagari", "numeric", "too-long",
        "en-prefix", "bho-namespace-or-list", "phrase-title", "empty", "duplicate",
    )}
    en_rows = 0
    for row in iter_rows(LL_SQL, "langlinks"):
        if row[1] != "en":
            continue
        en_rows += 1
        bho = pages.get(int(row[0]))
        if bho is None:
            skip["no-ns0-page"] += 1
            continue
        bho = bho.strip()
        en = row[2].strip()
        if not bho or not en:
            skip["empty"] += 1
            continue
        if len(bho) > 60 or len(en) > 60:
            skip["too-long"] += 1
            continue
        if "लिस्ट" in bho or ":" in bho:
            skip["bho-namespace-or-list"] += 1
            continue
        # encyclopedic-phrase titles ("दिल्ली में हवा प्रदूषण", election-year
        # articles) aren't dictionary headwords: cap at 3 words, no digits
        if len(bho.split()) > 3 or re.search(r"[0-9०-९]", bho):
            skip["phrase-title"] += 1
            continue
        if en.startswith(EN_SKIP_PREFIXES):
            skip["en-prefix"] += 1
            continue
        if NUMERIC_RE.match(bho):
            skip["numeric"] += 1
            continue
        if deva_ratio(bho) < 0.40:
            skip["not-devanagari"] += 1
            continue
        # Strip a trailing "(disambiguation)" only; keep other parentheticals.
        en = re.sub(r"\s*\(disambiguation\)$", "", en).strip()
        if not en:
            skip["empty"] += 1
            continue
        if bho in seen:
            skip["duplicate"] += 1
            continue
        seen.add(bho)
        entry = make_entry(bho, en)
        if any(0x0900 <= ord(c) <= 0x097F for c in en):
            review.append(entry)  # untranslated en title — not a usable gloss
        else:
            entries.append(entry)

    with OUT.open("w") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    if review:
        with REVIEW.open("w") as f:
            for e in review:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    print(f"langlinks.sql: {en_rows} en rows", file=sys.stderr)
    for k, v in skip.items():
        print(f"  skipped {k}: {v}", file=sys.stderr)
    print(f"Wrote {len(entries)} entries → {OUT}", file=sys.stderr)
    print(f"Wrote {len(review)} borderline entries → {REVIEW}", file=sys.stderr)

    sample = random.Random(42).sample(entries, min(8, len(entries)))
    for e in sample:
        print(f"  sample: {e['word']} → {e['senses'][0]['gloss']}", file=sys.stderr)


if __name__ == "__main__":
    main()
