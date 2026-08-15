#!/usr/bin/env python3
"""Score MT hypotheses against a reference with chrF2 (Popović 2015).

Pure-python chrF2 (character n-gram F-score, n=1..6, β=2) — matches
sacrebleu's chrF2 signature closely enough for tracking progress; use
sacrebleu for publishable numbers.

Usage:
    python3 eval/score.py --hyp hyps.txt --ref data/corpus/parallel/flores200-devtest-EVAL-ONLY.jsonl --field bho
    python3 eval/score.py --hyp hyps.txt --ref refs.txt

--ref accepts either a plain text file (one reference per line) or a
corpus JSONL file (pass --field bho|en to select the reference side).
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def char_ngrams(text: str, n: int) -> Counter:
    text = " ".join(text.split())  # normalize whitespace, keep spaces (chrF default: no ws) —
    text = text.replace(" ", "")   # sacrebleu chrF removes whitespace by default
    return Counter(text[i : i + n] for i in range(len(text) - n + 1))


def chrf(hyps: list[str], refs: list[str], max_n: int = 6, beta: float = 2.0) -> float:
    total_prec = total_rec = 0.0
    counted = 0
    for n in range(1, max_n + 1):
        match = hyp_total = ref_total = 0
        for h, r in zip(hyps, refs):
            hg, rg = char_ngrams(h, n), char_ngrams(r, n)
            match += sum((hg & rg).values())
            hyp_total += sum(hg.values())
            ref_total += sum(rg.values())
        if hyp_total and ref_total:
            total_prec += match / hyp_total
            total_rec += match / ref_total
            counted += 1
    if not counted:
        return 0.0
    prec, rec = total_prec / counted, total_rec / counted
    if prec + rec == 0:
        return 0.0
    b2 = beta * beta
    return 100 * (1 + b2) * prec * rec / (b2 * prec + rec)


def read_lines(path: Path, field: str | None) -> list[str]:
    lines = path.read_text().splitlines()
    if path.suffix == ".jsonl":
        if not field:
            sys.exit("--field bho|en required for JSONL references")
        return [json.loads(l)[field] for l in lines]
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hyp", required=True, type=Path)
    ap.add_argument("--ref", required=True, type=Path)
    ap.add_argument("--field", choices=("bho", "en"))
    args = ap.parse_args()

    hyps = read_lines(args.hyp, None)
    refs = read_lines(args.ref, args.field)
    if len(hyps) != len(refs):
        sys.exit(f"line count mismatch: {len(hyps)} hyps vs {len(refs)} refs")
    print(f"chrF2 = {chrf(hyps, refs):.2f}  ({len(hyps)} segments)")


if __name__ == "__main__":
    main()
