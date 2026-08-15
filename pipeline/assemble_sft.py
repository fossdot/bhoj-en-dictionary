#!/usr/bin/env python3
"""Assemble the final SFT training bundle from dictionary + corpus data.

Combines:
  data/training/instructions.jsonl            (dictionary-derived define/translate tasks)
  data/corpus/parallel/*.jsonl                (translation pairs → chat format)

Excludes by default:
  *EVAL-ONLY* files (FLORES-200 — reserved for benchmarking, never train on these)
  *-NC files (CC-BY-NC — pass --include-nc to add them, producing the NC bundle)

Outputs:
  data/training/sft.jsonl        (commercial-safe bundle)
  data/training/sft-nc.jsonl     (with --include-nc: adds BHLTR; non-commercial use only)

Usage:
    python3 pipeline/assemble_sft.py [--include-nc]
"""

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAR = ROOT / "data" / "corpus" / "parallel"
TRAIN = ROOT / "data" / "training"

# varied prompt templates so the model doesn't overfit one phrasing
BHO_EN = [
    "Translate this Bhojpuri sentence to English: {src}",
    "What does this mean in English? {src}",
    "Translate from Bhojpuri to English:\n{src}",
    "एह भोजपुरी वाक्य के अंग्रेजी में अनुवाद करीं: {src}",
]
EN_BHO = [
    "Translate to Bhojpuri: {src}",
    "How do you say this in Bhojpuri? {src}",
    "Translate this English sentence into Bhojpuri:\n{src}",
    "एकर भोजपुरी में अनुवाद करीं: {src}",
]


def pair_to_chat(row: dict, rng: random.Random) -> dict:
    if rng.random() < 0.5:
        tpl, src, tgt, task = rng.choice(BHO_EN), row["bho"], row["en"], "translate-bho-en"
    else:
        tpl, src, tgt, task = rng.choice(EN_BHO), row["en"], row["bho"], "translate-en-bho"
    return {
        "messages": [
            {"role": "user", "content": tpl.format(src=src)},
            {"role": "assistant", "content": tgt},
        ],
        "source": row["source"],
        "task": task,
    }


def main() -> None:
    include_nc = "--include-nc" in sys.argv
    rng = random.Random(42)
    out_name = "sft-nc.jsonl" if include_nc else "sft.jsonl"

    rows = []
    instr = TRAIN / "instructions.jsonl"
    if instr.exists():
        rows += [json.loads(l) for l in instr.open()]

    for path in sorted(PAR.glob("*.jsonl")):
        if "EVAL-ONLY" in path.name:
            continue
        if path.name.endswith("-NC.jsonl") and not include_nc:
            continue
        for line in path.open():
            rows.append(pair_to_chat(json.loads(line), rng))

    rng.shuffle(rows)
    seen = set()
    n = 0
    with (TRAIN / out_name).open("w") as f:
        for r in rows:
            key = r["messages"][0]["content"]
            if key in seen:
                continue
            seen.add(key)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1

    by_task: dict[str, int] = {}
    for r in rows:
        by_task[r["task"]] = by_task.get(r["task"], 0) + 1
    print(f"{n} examples → {TRAIN / out_name}", file=sys.stderr)
    for task, count in sorted(by_task.items()):
        print(f"  {task}: {count}", file=sys.stderr)


if __name__ == "__main__":
    main()
