#!/usr/bin/env python3
"""Convert canonical JSONL entries into dictpress bulk-import CSV.

dictpress CSV format (https://dict.press/docs/import/), one row per line:
  col 0: "-" main entry | "^" definition of the preceding main entry
  col 1: initial (uppercase first char; dictpress auto-fills if blank)
  col 2: content (the word / definition text)
  col 3: language id (must match dictpress config)
  col 4: notes
  col 5: tokenizer ("default:<lang>" or blank when tokens are supplied)
  col 6: space-separated search tokens (blank when a tokenizer is set)
  col 7: tags, pipe-separated
  col 8: phones, pipe-separated
  col 9: definition types (parts of speech) for "^" rows, pipe-separated
  col 10: meta JSON

Usage:
    python3 pipeline/to_dictpress.py data/canonical/*.jsonl > dictpress/import.csv
"""

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LANG_BHO = "bhojpuri"
LANG_EN = "english"


FREQ_CACHE = ROOT / "data" / "corpus" / "word-freq.json"
CORPUS = ROOT / "data" / "corpus" / "mono" / "all-dedup-lid-bho.txt"
# committed, headwords-only copy of the frequency cache so the server (which has
# no corpus) ranks results the same way as a laptop with the full corpus
HEADWORD_FREQ = ROOT / "dictpress" / "headword-freq.json"


def corpus_freq() -> dict[str, int]:
    """Headword frequency in the LID-filtered Bhojpuri corpus, for ranking.
    Returns {} when the corpus isn't built (ordering then falls back to length)."""
    if FREQ_CACHE.exists():
        return json.loads(FREQ_CACHE.read_text())
    if HEADWORD_FREQ.exists():
        return json.loads(HEADWORD_FREQ.read_text())
    if not CORPUS.exists():
        return {}
    counts: Counter[str] = Counter()
    word_re = re.compile(r"[\u0900-\u097F]+")
    with CORPUS.open() as f:
        for line in f:
            counts.update(word_re.findall(line))
    freq = {w: c for w, c in counts.items() if c > 1}
    FREQ_CACHE.parent.mkdir(parents=True, exist_ok=True)
    FREQ_CACHE.write_text(json.dumps(freq, ensure_ascii=False))
    return freq


def entry_rows(e: dict) -> list[list[str]]:
    word = e["word"]
    phones = "|".join(e.get("phones", []) + e.get("translit", []))
    tags = "|".join(e.get("tags", []) + [f"script:{e['script']}"] if e.get("script") else e.get("tags", []))
    meta = {"source": e.get("source", ""), "license": e.get("license", "")}

    rows = [[
        "-", "", word, LANG_BHO, "",
        "lua:indicphone_hi.lua", "", tags, phones,
        "",  # definition types are only valid on "^" rows
        json.dumps(meta, ensure_ascii=False),
    ]]
    for sense in e["senses"]:
        note_parts = []
        for ex in sense.get("examples", []):
            if "en" in ex:
                note_parts.append(f"{ex['bho']} — {ex['en']}")
            else:
                note_parts.append(ex["bho"])
        rows.append([
            "^", "", sense["gloss"], LANG_EN, "; ".join(note_parts),
            f"default:{LANG_EN}", "", "", "",
            sense.get("pos", ""), "",
        ])
    return rows


def merge(entries: list[dict]) -> dict:
    """Merge duplicate headwords from different sources into one entry."""
    base = entries[0]
    for other in entries[1:]:
        for field in ("translit", "phones", "tags"):
            base[field] = list(dict.fromkeys(base.get(field, []) + other.get(field, [])))
        seen = {s["gloss"].lower() for s in base["senses"]}
        base["senses"] += [s for s in other["senses"] if s["gloss"].lower() not in seen]
    return base


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        sys.exit("usage: to_dictpress.py <canonical.jsonl> [...]")

    # group by headword across all source files (file order = source priority)
    by_word: dict[str, list[dict]] = {}
    for path in paths:
        with path.open() as f:
            for line in f:
                e = json.loads(line)
                by_word.setdefault(e["word"], []).append(e)

    w = csv.writer(sys.stdout)
    n_defs = 0
    # dictpress ranks search results by import order (row weight), so emit the
    # most important headwords first: entries sharing a phonetic hash are
    # ranked by corpus frequency, then compactness. Without this, a rare short
    # word (पना) outranks the common word the user typed (पानी).
    freq = corpus_freq()
    for word in sorted(by_word, key=lambda x: (-freq.get(x, 0), len(x.split()), len(x), x)):
        rows = entry_rows(merge(by_word[word]))
        w.writerows(rows)
        n_defs += len(rows) - 1
    print(f"{len(by_word)} entries, {n_defs} definitions", file=sys.stderr)


if __name__ == "__main__":
    main()
