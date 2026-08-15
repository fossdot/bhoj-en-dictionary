#!/usr/bin/env python3
"""Convert GATITOS (Google's low-resource MT lexicons, part of the SMOL
release, CC-BY-4.0) into canonical entries.

Input (downloaded from https://huggingface.co/datasets/google/smol):
  data/raw/gatitos/bho_en.jsonl   {"src": <bho>, "trgs": [<en>, ...]}
  data/raw/gatitos/en_bho.jsonl   {"src": <en>, "trgs": [<bho>, ...]}

Both directions are folded into bho-headword entries.

Output: data/canonical/gatitos-bho.jsonl
"""

import json
import sys
from pathlib import Path

from fetch_wiktionary import detect_script

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "gatitos"
OUT = ROOT / "data" / "canonical" / "gatitos-bho.jsonl"


def main() -> None:
    by_word: dict[str, dict] = {}

    def entry(word: str) -> dict:
        return by_word.setdefault(word, {
            "word": word,
            "lang": "bho",
            "script": detect_script(word),
            "translit": [],
            "phones": [],
            "tags": [],
            "senses": [],
            "source": "GATITOS (Google SMOL)",
            "source_url": "https://huggingface.co/datasets/google/smol",
            "license": "CC-BY-4.0",
        })

    def add_sense(e: dict, gloss: str) -> None:
        if gloss and not any(s["gloss"].lower() == gloss.lower() for s in e["senses"]):
            e["senses"].append({"pos": "", "gloss": gloss, "examples": []})

    n_pairs = 0
    for row in (RAW / "bho_en.jsonl").open():
        d = json.loads(row)
        word = d["src"].strip()
        glosses = [t.strip() for t in d["trgs"] if t.strip()]
        if word and glosses:
            add_sense(entry(word), ", ".join(glosses))
            n_pairs += len(glosses)

    for row in (RAW / "en_bho.jsonl").open():
        d = json.loads(row)
        en = d["src"].strip()
        for bho in d["trgs"]:
            bho = bho.strip()
            if bho and en:
                add_sense(entry(bho), en)
                n_pairs += 1

    with OUT.open("w") as f:
        for e in by_word.values():
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"{n_pairs} pairs → {len(by_word)} bho headwords → {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
