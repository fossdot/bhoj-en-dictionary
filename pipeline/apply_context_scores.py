#!/usr/bin/env python3
"""Act on data/cleaning/context-scores.jsonl.

Removes the entries the corpus actively argues against, and labels the
survivors with the evidence so the review app can work worst-first instead
of alphabetically.

Removal rules (both apply only to the `unverified` tier — entries no source
ever asserted were Bhojpuri):

  hindi-context   bho_ratio < --ratio-min on >= --support-min marked lines.
                  The word occurs in Bhojpuri-labelled text but keeps Hindi
                  company: Hindi grammar clusters around it.
  unattested      zero occurrences anywhere in the mono corpus, which voids
                  the corpus-frequency attestation these entries rest on.

Survivors in that tier get tags: conf:high / conf:medium / conf:low /
conf:unknown, plus a bho_ratio field.

Usage:
    python3 pipeline/apply_context_scores.py            # report only
    python3 pipeline/apply_context_scores.py --apply
"""

import argparse
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANON = ROOT / "data" / "canonical"
CLEAN = ROOT / "data" / "cleaning"


def nfc(s):
    return unicodedata.normalize("NFC", s)


def confidence(score):
    """How much the corpus has to say about this word."""
    if score is None or score["support"] < 10:
        return "conf:unknown"
    if score["support"] >= 30 and score["bho_ratio"] >= 0.90:
        return "conf:high"
    if score["bho_ratio"] >= 0.85:
        return "conf:medium"
    return "conf:low"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--ratio-min", type=float, default=0.80)
    ap.add_argument("--support-min", type=int, default=30)
    args = ap.parse_args()

    scores = {}
    for line in (CLEAN / "context-scores.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        scores[nfc(d["word"])] = d

    tier = {}
    for line in (CLEAN / "triage.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        tier[nfc(d["word"])] = d["tier"]

    stats = Counter()
    removed, kept_rows = [], {}

    for path in sorted(CANON.glob("*.jsonl")):
        out = []
        for line in path.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            w = nfc(e["word"])
            sc = scores.get(w)
            is_unverified = tier.get(w) == "unverified"

            reason = None
            if is_unverified and sc:
                if sc["lines"] == 0:
                    reason = "unattested: absent from the mono corpus"
                elif (sc["support"] >= args.support_min
                      and sc["bho_ratio"] < args.ratio_min):
                    reason = (f"hindi-context: bho_ratio {sc['bho_ratio']:.2f} "
                              f"over {sc['support']} marked lines")

            if reason:
                stats[reason.split(":")[0]] += 1
                removed.append({**e, "_file": path.name, "_reason": reason,
                                "_bho_ratio": sc["bho_ratio"], "_support": sc["support"]})
                continue

            if is_unverified:
                tag = confidence(sc)
                if tag not in e.get("tags", []):
                    e.setdefault("tags", []).append(tag)
                if sc and sc["support"] >= 10:
                    e["bho_ratio"] = sc["bho_ratio"]
                stats[tag] += 1
            out.append(e)
        kept_rows[path] = out

    print(f"{'removed':>10}  {stats['unattested']:5}  unattested (absent from corpus)")
    print(f"{'':>10}  {stats['hindi-context']:5}  hindi-context "
          f"(ratio < {args.ratio_min} on >= {args.support_min} lines)")
    print(f"{'':>10}  {len(removed):5}  TOTAL")
    print()
    for t in ("conf:high", "conf:medium", "conf:low", "conf:unknown"):
        print(f"{'tagged':>10}  {stats[t]:5}  {t}")
    total = sum(len(v) for v in kept_rows.values())
    print(f"\n{'remaining':>10}  {total:5}  entries")

    if not args.apply:
        print("\nreport only; pass --apply to write", file=sys.stderr)
        return

    for path, rows in kept_rows.items():
        with path.open("w", encoding="utf-8") as fh:
            for e in rows:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    with (CLEAN / "context-removed.jsonl").open("w", encoding="utf-8") as fh:
        for e in removed:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"wrote canonical files + {CLEAN/'context-removed.jsonl'}", file=sys.stderr)


if __name__ == "__main__":
    main()
