#!/usr/bin/env python3
"""Extract FineWeb-2 and finepdfs bho_Deva parquet shards to plain text.

Runs under the project venv (needs pyarrow):
    .venv/bin/python pipeline/extract_parquet.py

Outputs data/raw/{fineweb2,finepdfs}/extracted.txt which build_corpus.py
then folds into data/corpus/mono/.

finepdfs text comes from PDF text layers where Devanagari is often stored in
*visual* order (ि before its consonant, matras split off by spaces). We apply
the standard mechanical repairs; the language audit downstream shows how much
Hindi contamination remains per file.
"""

import re
import sys
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
CONS = r"(?:[क-ह]़?)"  # consonant + optional nukta (covers क़ ज़ ड़ ढ़ फ़ य़ decomposed or not)
# visual-order i-matra: ि stored before the consonant (+optional conjunct) it belongs to
I_MATRA_FIX = re.compile(rf"ि({CONS}(?:्{CONS})*)")
# matra/sign separated from its consonant by a stray space (PDF extraction artifact)
SPLIT_MATRA_FIX = re.compile(rf"({CONS}) ([ा-ौंःँ़])")


def fix_pdf_text(text: str) -> str:
    # single pass: the regex already consumes full conjunct chains (क्ष, त्र, …)
    text = I_MATRA_FIX.sub(r"\1ि", text)
    text = SPLIT_MATRA_FIX.sub(r"\1\2", text)
    return text


def extract(name: str, fix: bool, min_dev_ratio: float = 0.4) -> None:
    d = RAW / name
    shards = sorted(d.glob("*.parquet"))
    if not shards:
        return
    n = 0
    with (d / "extracted.txt").open("w") as out:
        for shard in shards:
            table = pq.read_table(shard, columns=["text"])
            for cell in table["text"]:
                text = cell.as_py()
                if fix:
                    text = fix_pdf_text(text)
                for ln in text.splitlines():
                    ln = ln.strip()
                    if ln and len(DEVANAGARI_RE.findall(ln)) > len(ln) * min_dev_ratio:
                        out.write(ln + "\n")
                        n += 1
    print(f"  {name}: {n} lines → {d}/extracted.txt", file=sys.stderr)


if __name__ == "__main__":
    extract("fineweb2", fix=False)
    extract("finepdfs", fix=True)
