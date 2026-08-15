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
import sys
from pathlib import Path

LANG_BHO = "bhojpuri"
LANG_EN = "english"


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
    for word in sorted(by_word):
        rows = entry_rows(merge(by_word[word]))
        w.writerows(rows)
        n_defs += len(rows) - 1
    print(f"{len(by_word)} entries, {n_defs} definitions", file=sys.stderr)


if __name__ == "__main__":
    main()
