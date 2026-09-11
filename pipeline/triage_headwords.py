#!/usr/bin/env python3
"""Triage canonical headwords by strength of Bhojpuri evidence.

The dictionary is assembled from sources of very uneven authority. This
sorts every entry into a tier and says why, so that low-evidence material
can be dropped or routed to native-speaker review instead of shipping as
if a lexicographer had signed off on it.

Tiers
  attested        a source explicitly labelled the word Bhojpuri
                  (en-Wiktionary Bhojpuri lemmas, GATITOS, community)
  shared-attested Hindi-sourced, but the headword is independently
                  attested by one of the sources above -> keep
  proper-noun     bhwiki langlink whose gloss is an encyclopedia title
                  (place, person, work) -> not dictionary content
  weak-align      IBM-1 alignment below --align-min, no other evidence
  loanword        English written in Devanagari, no other evidence
  unverified      Hindi-sourced, corpus-frequency attestation only.
                  Genuine Bhojpuri and Hindi-only words both live here;
                  only a speaker can separate them.

Usage
    python3 pipeline/triage_headwords.py              # report only
    python3 pipeline/triage_headwords.py --apply      # drop the drop-tiers
    python3 pipeline/triage_headwords.py --apply --drop unverified
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
OUT_DIR = ROOT / "data" / "cleaning"

# Sources that assert "this word is Bhojpuri", as opposed to inferring it.
ATTESTING = {
    "wiktionary-bho.jsonl",
    "gatitos-bho.jsonl",
    "wiktionary-translations-bho.jsonl",
    "community-bho.jsonl",
}

DROP_BY_DEFAULT = ("proper-noun", "weak-align")

DEVA = re.compile(r"[ऀ-ॿ]")
LATN = re.compile(r"[A-Za-z]")

# A gloss that is mostly Capitalised words is an encyclopedia title, not a
# definition: "Fatehpur district", "A. K. Hangal", "St. Lawrence River".
TITLE_STOP = {"a", "an", "the", "of", "in", "on", "at", "and", "or", "de", "da"}


def title_like(gloss: str) -> bool:
    toks = [t for t in re.split(r"\s+", gloss.strip()) if t]
    if not toks:
        return False
    sig = [t for t in toks if t.lower().strip("(),.") not in TITLE_STOP]
    if not sig:
        return False
    caps = sum(1 for t in sig if t[:1].isupper())
    return caps / len(sig) >= 0.5


def load():
    entries = []
    for path in sorted(CANON.glob("*.jsonl")):
        for lineno, line in enumerate(path.open(encoding="utf-8"), 1):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            d["_file"] = path.name
            d["_lineno"] = lineno
            entries.append(d)
    return entries


def classify(entries, align_min: float):
    attested = {
        unicodedata.normalize("NFC", e["word"])
        for e in entries
        if e["_file"] in ATTESTING
    }

    for e in entries:
        word = unicodedata.normalize("NFC", e["word"])
        glosses = [s.get("gloss", "") for s in e.get("senses", [])]
        first = glosses[0] if glosses else ""
        tags = set(e.get("tags", []))
        has_other_evidence = word in attested

        if e["_file"] in ATTESTING:
            e["_tier"], e["_why"] = "attested", f"source asserts Bhojpuri ({e['_file']})"

        elif "src:hi-descendant" in tags:
            e["_tier"], e["_why"] = "attested", "listed as a Bhojpuri descendant on the Hindi entry"

        elif "src:bhwiki-langlinks" in tags and title_like(first):
            e["_tier"], e["_why"] = "proper-noun", f"Wikipedia article title: {first!r}"

        elif has_other_evidence:
            e["_tier"], e["_why"] = "shared-attested", "headword independently attested by an asserting source"

        elif "src:aligned" in tags:
            scores = e.get("align_scores") or {}
            best = max(scores.values(), default=0.0)
            if best < align_min:
                e["_tier"], e["_why"] = "weak-align", f"best IBM-1 alignment {best:.2f} < {align_min}"
            else:
                e["_tier"], e["_why"] = "unverified", f"alignment only, best {best:.2f}"

        elif LATN.search(word) and not DEVA.search(word):
            e["_tier"], e["_why"] = "loanword", "headword is Latin script"

        elif "src:hi-cognate" in tags:
            e["_tier"], e["_why"] = "unverified", "Hindi entry, Bhojpuri-corpus frequency only"

        else:
            e["_tier"], e["_why"] = "unverified", f"no asserting source ({e['_file']})"

    return entries


def report(entries, align_min, drop):
    tiers = Counter(e["_tier"] for e in entries)
    per_file = defaultdict(Counter)
    for e in entries:
        per_file[e["_file"]][e["_tier"]] += 1

    order = ["attested", "shared-attested", "unverified", "loanword", "weak-align", "proper-noun"]
    total = len(entries)

    lines = [
        "# Headword triage",
        "",
        "Generated by `pipeline/triage_headwords.py`. Tiers rank how strongly a",
        "source asserts that a headword is Bhojpuri, not how common the word is.",
        "",
        f"- entries: **{total}**",
        f"- unique headwords: **{len({e['word'] for e in entries})}**",
        f"- alignment floor: {align_min}",
        f"- dropped by this run: {', '.join(drop) if drop else '(report only)'}",
        "",
        "| tier | entries | share | meaning |",
        "|---|---:|---:|---|",
    ]
    meaning = {
        "attested": "a source explicitly labelled it Bhojpuri",
        "shared-attested": "Hindi-sourced but independently attested",
        "unverified": "inferred only — needs a speaker",
        "loanword": "Latin script in a Bhojpuri field",
        "weak-align": "statistical alignment noise",
        "proper-noun": "encyclopedia title, not a dictionary word",
    }
    for t in order:
        n = tiers.get(t, 0)
        if n:
            lines.append(f"| `{t}` | {n} | {100*n/total:.0f}% | {meaning[t]} |")

    lines += ["", "## By source file", "", "| file | " + " | ".join(f"`{t}`" for t in order) + " |",
              "|---" * (len(order) + 1) + "|"]
    for f in sorted(per_file):
        row = " | ".join(str(per_file[f].get(t, 0)) for t in order)
        lines.append(f"| `{f}` | {row} |")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="rewrite canonical files")
    ap.add_argument("--align-min", type=float, default=0.30)
    ap.add_argument("--drop", nargs="*", default=list(DROP_BY_DEFAULT),
                    help=f"tiers to remove (default: {' '.join(DROP_BY_DEFAULT)})")
    args = ap.parse_args()

    entries = classify(load(), args.align_min)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with (OUT_DIR / "triage.jsonl").open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps({
                "id": f"{e['_file'].replace('.jsonl','')}:{e['word']}",
                "word": e["word"], "file": e["_file"], "line": e["_lineno"],
                "tier": e["_tier"], "why": e["_why"],
                "gloss": "; ".join(s.get("gloss", "") for s in e.get("senses", []))[:200],
            }, ensure_ascii=False) + "\n")

    drop = [t for t in args.drop if t]
    text = report(entries, args.align_min, drop if args.apply else [])
    (OUT_DIR / "TRIAGE.md").write_text(text, encoding="utf-8")
    print(text)

    if not args.apply:
        print(f"\nreport only. wrote {OUT_DIR/'TRIAGE.md'} and {OUT_DIR/'triage.jsonl'}",
              file=sys.stderr)
        return

    dropset = set(drop)

    # Log the casualties before stripping bookkeeping keys off the survivors.
    with (OUT_DIR / "triage-removed.jsonl").open("w", encoding="utf-8") as fh:
        for e in entries:
            if e["_tier"] in dropset:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")

    by_file = defaultdict(list)
    for e in entries:
        by_file[e["_file"]].append(e)

    kept_log = []
    for path in sorted(CANON.glob("*.jsonl")):
        rows = by_file.get(path.name, [])
        keep = [e for e in rows if e["_tier"] not in dropset]
        if len(keep) != len(rows):
            kept_log.append((path.name, len(rows), len(rows) - len(keep)))
        with path.open("w", encoding="utf-8") as fh:
            for e in keep:
                fh.write(json.dumps(
                    {k: v for k, v in e.items() if not k.startswith("_")},
                    ensure_ascii=False) + "\n")

    print("\nremoved:", file=sys.stderr)
    for name, before, removed in kept_log:
        print(f"  {name:42} -{removed} of {before}", file=sys.stderr)


if __name__ == "__main__":
    main()
