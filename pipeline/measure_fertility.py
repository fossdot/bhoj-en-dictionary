#!/usr/bin/env python3
"""Measure tokenizer fertility (tokens per word) on the Bhojpuri corpus.

Lower is better: a tokenizer that shreds Devanagari into bytes wastes
context window and typically transfers worse. Tokenizer files are downloaded
into data/raw/tokenizers/ (see README for repos; gated ones like Gemma/Llama
need a manual download with an HF token).

    .venv/bin/python pipeline/measure_fertility.py
"""

import sys
from pathlib import Path

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parent.parent
TOK_DIR = ROOT / "data" / "raw" / "tokenizers"
CORPUS = ROOT / "data" / "corpus" / "mono" / "all-dedup-lid-bho.txt"
SAMPLE_LINES = 20000


def main() -> None:
    lines = []
    with CORPUS.open() as f:
        for i, ln in enumerate(f):
            if i >= SAMPLE_LINES:
                break
            lines.append(ln.strip())
    words = sum(len(ln.split()) for ln in lines)
    chars = sum(len(ln) for ln in lines)
    print(f"sample: {len(lines)} lines, {words} words, {chars} chars\n", file=sys.stderr)

    rows = []
    for path in sorted(TOK_DIR.glob("*.json")):
        tok = Tokenizer.from_file(str(path))
        n_tokens = sum(len(tok.encode(ln).ids) for ln in lines)
        rows.append((path.stem, n_tokens, n_tokens / words, chars / n_tokens))

    print(f"{'tokenizer':<14} {'tokens':>10} {'tokens/word':>12} {'chars/token':>12}")
    for name, n, tpw, cpt in sorted(rows, key=lambda r: r[2]):
        print(f"{name:<14} {n:>10} {tpw:>12.2f} {cpt:>12.2f}")


if __name__ == "__main__":
    main()
