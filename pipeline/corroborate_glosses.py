#!/usr/bin/env python3
"""Check Hindi-derived glosses against independent English evidence.

Most of the dictionary's glosses were carried over from Hindi Wiktionary.
The headwords are attested Bhojpuri (see attest_headwords.py), but nobody
had checked that the English on the other side is right, and that is a
separate question a corpus cannot answer.

Two sources give an English gloss that did not come from Hindi Wiktionary:
GATITOS, which Google built as a bho->en lexicon, and the IBM-1 alignments
over NLLB professional translations. Where either covers a headword, its
English can be compared against ours.

  gloss:corroborated  an independent source gives the same meaning
  gloss:conflict      an independent source disagrees — look at it

Matching is deliberately loose: "demography" against "demographics", or
"curve" against "a curve; bent; crooked", are the same answer, and
treating them as conflicts buries the real ones.

Usage:
    python3 pipeline/corroborate_glosses.py            # report only
    python3 pipeline/corroborate_glosses.py --apply
"""

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANON = ROOT / "data" / "canonical"
CLEAN = ROOT / "data" / "cleaning"

# Sources whose English did not come from Hindi Wiktionary.
INDEPENDENT = ("gatitos-bho.jsonl", "aligned-bho.jsonl", "aligned-bho-review.jsonl")

SPLIT = re.compile(r"[;,()\[\]/]|\bor\b|\band\b")
STOP = {"a", "an", "the", "of", "to", "in", "on", "at", "is", "be", "as",
        "used", "esp", "especially", "etc", "also", "someone", "something"}


def nfc(s):
    return unicodedata.normalize("NFC", s)


def stem(w):
    """Crude suffix strip so demography/demographics/demographic collapse."""
    w = w.strip().lower()
    for suf in ("ically", "ations", "ation", "ities", "ity", "ics", "ism",
                "ness", "ing", "ies", "ed", "es", "s", "y", "ic", "al"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def terms(gloss):
    out = set()
    for part in SPLIT.split(gloss or ""):
        part = part.strip().lower()
        if not part:
            continue
        words = [w for w in re.findall(r"[a-z']+", part) if w not in STOP]
        if not words:
            continue
        out.add(" ".join(words))
        out.update(words)
    return {stem(t) for t in out if t}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    tier = {nfc(json.loads(l)["word"]): json.loads(l)["tier"]
            for l in (CLEAN / "triage.jsonl").open(encoding="utf-8")}

    per_source = {}
    for name in INDEPENDENT:
        p = CANON / name
        idx = defaultdict(set)
        if p.exists():
            for line in p.open(encoding="utf-8"):
                if not line.strip():
                    continue
                d = json.loads(line)
                for s in d.get("senses", []):
                    idx[nfc(d["word"])] |= terms(s.get("gloss", ""))
        per_source[name] = idx

    def evidence_for(word, own_file):
        """Independent English, excluding the entry's own source file."""
        out = set()
        for name, idx in per_source.items():
            if name == own_file:
                continue
            out |= idx.get(word, set())
        return out

    files = {p: [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]
             for p in sorted(CANON.glob("*.jsonl"))}

    stats = Counter()
    conflicts = []
    for path, rows in files.items():
        for e in rows:
            w = nfc(e["word"])
            if tier.get(w) != "unverified":
                continue
            theirs = evidence_for(w, path.name)
            if not theirs:
                continue
            ours = set()
            for s in e.get("senses", []):
                ours |= terms(s.get("gloss", ""))
            hit = bool(ours & theirs) or any(
                a in b or b in a for a in ours for b in theirs if len(a) > 3 and len(b) > 3)
            tag = "gloss:corroborated" if hit else "gloss:conflict"
            stats[tag] += 1
            e.setdefault("tags", [])
            if tag not in e["tags"]:
                e["tags"].append(tag)
            if not hit:
                conflicts.append({
                    "word": e["word"], "file": path.name,
                    "ours": "; ".join(s.get("gloss", "") for s in e["senses"])[:160],
                    "independent": "; ".join(sorted(theirs))[:120],
                })

    n_unv = sum(1 for t in tier.values() if t == "unverified")
    print(f"unverified entries                : {n_unv}")
    print(f"  independently corroborated      : {stats['gloss:corroborated']}")
    print(f"  independent source disagrees    : {stats['gloss:conflict']}")
    checked = stats['gloss:corroborated'] + stats['gloss:conflict']
    if checked:
        print(f"  agreement rate                  : "
              f"{100*stats['gloss:corroborated']/checked:.0f}%")
    print(f"  no independent English available : {n_unv - checked}")

    if conflicts:
        print("\nconflicts (ours | independent):")
        for c in conflicts[:12]:
            print(f"  {c['word'][:14]:16} {c['ours'][:48]:50} | {c['independent'][:34]}")

    if not args.apply:
        print("\nreport only; pass --apply to write", file=sys.stderr)
        return

    for path, rows in files.items():
        with path.open("w", encoding="utf-8") as fh:
            for e in rows:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    with (CLEAN / "gloss-conflicts.jsonl").open("w", encoding="utf-8") as fh:
        for c in conflicts:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"\nwrote canonical files + {CLEAN/'gloss-conflicts.jsonl'}", file=sys.stderr)


if __name__ == "__main__":
    main()
