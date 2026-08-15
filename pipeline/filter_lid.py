#!/usr/bin/env python3
"""Produce the LID-filtered training corpus: keep only lines the VarDial
classifier (data/lid/model.joblib, from train_lid.py) labels BHO.

    .venv/bin/python pipeline/filter_lid.py

Input:  data/corpus/mono/all-dedup.txt
Output: data/corpus/mono/all-dedup-lid-bho.txt
"""

import sys
from pathlib import Path

import joblib

ROOT = Path(__file__).resolve().parent.parent
MONO = ROOT / "data" / "corpus" / "mono"
BATCH = 20000


def main() -> None:
    model = joblib.load(ROOT / "data" / "lid" / "model.joblib")
    src = MONO / "all-dedup.txt"
    dst = MONO / "all-dedup-lid-bho.txt"
    kept = total = 0
    with src.open() as f, dst.open("w") as out:
        batch: list[str] = []

        def flush() -> None:
            nonlocal kept
            if not batch:
                return
            for ln, pred in zip(batch, model.predict(batch)):
                # short lines carry too little signal for the classifier — keep them
                if pred == "BHO" or len(ln) <= 25:
                    out.write(ln + "\n")
                    kept += 1
            batch.clear()

        for ln in f:
            ln = ln.rstrip("\n")
            if not ln:
                continue
            total += 1
            batch.append(ln)
            if len(batch) >= BATCH:
                flush()
        flush()
    print(f"kept {kept}/{total} lines → {dst}", file=sys.stderr)


if __name__ == "__main__":
    main()
