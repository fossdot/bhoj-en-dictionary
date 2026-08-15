#!/usr/bin/env python3
"""Export canonical JSONL into LLM training-ready datasets.

Produces (under data/training/):
  lexicon.tsv        bho word <tab> english gloss — seed bilingual lexicon
  parallel.jsonl     {"bho": ..., "en": ...} sentence/phrase pairs from usage examples
  instructions.jsonl chat-format instruction data (define/translate tasks)

Usage:
    python3 pipeline/to_training.py data/canonical/*.jsonl
"""

import json
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "training"

POS_LABEL = {
    "noun": "noun", "propernoun": "proper noun", "verb": "verb",
    "adjective": "adjective", "adverb": "adverb", "pronoun": "pronoun",
    "conjunction": "conjunction", "postposition": "postposition",
    "interjection": "interjection", "numeral": "numeral",
    "determiner": "determiner", "classifier": "classifier",
    "suffix": "suffix", "prefix": "prefix", "phrase": "phrase",
    "proverb": "proverb", "particle": "particle", "preposition": "preposition",
}


def load(paths: list[Path]):
    for path in paths:
        with path.open() as f:
            for line in f:
                yield json.loads(line)


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        sys.exit("usage: to_training.py <canonical.jsonl> [...]")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    lexicon, parallel, instructions = [], [], []

    for e in load(paths):
        word = e["word"]
        src = e.get("source", "")
        for sense in e["senses"]:
            gloss, pos = sense["gloss"], sense.get("pos", "")
            # skip pure cross-reference senses — not real glosses
            if gloss.startswith(("script variant of", "Kaithi spelling of", "alternative form of")):
                continue
            lexicon.append((word, gloss, pos, src))
            instructions.append({
                "messages": [
                    {"role": "user", "content": f"What does the Bhojpuri word \"{word}\" mean in English?"},
                    {"role": "assistant", "content": f"\"{word}\" is a Bhojpuri {POS_LABEL.get(pos, 'word')} meaning: {gloss}."},
                ],
                "source": src, "task": "define",
            })
            for ex in sense.get("examples", []):
                if "en" not in ex:
                    continue
                parallel.append({"bho": ex["bho"], "en": ex["en"], "source": src})
                instructions.append({
                    "messages": [
                        {"role": "user", "content": f"Translate this Bhojpuri sentence to English: {ex['bho']}"},
                        {"role": "assistant", "content": ex["en"]},
                    ],
                    "source": src, "task": "translate-bho-en",
                })
                instructions.append({
                    "messages": [
                        {"role": "user", "content": f"Translate to Bhojpuri: {ex['en']}"},
                        {"role": "assistant", "content": ex["bho"]},
                    ],
                    "source": src, "task": "translate-en-bho",
                })

    with (OUT_DIR / "lexicon.tsv").open("w") as f:
        f.write("bho\ten\tpos\tsource\n")
        for row in sorted(set(lexicon)):
            f.write("\t".join(row) + "\n")
    for name, rows in (("parallel.jsonl", parallel), ("instructions.jsonl", instructions)):
        with (OUT_DIR / name).open("w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(
        f"lexicon: {len(set(lexicon))} pairs | parallel: {len(parallel)} sentence pairs | "
        f"instructions: {len(instructions)} examples → {OUT_DIR}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
