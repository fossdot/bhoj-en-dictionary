#!/usr/bin/env python3
"""Drop shared Indo-Aryan vocabulary the corpus does not place firmly in Bhojpuri.

Most of the dictionary below the attested tier is vocabulary Bhojpuri and Hindi
both use. `score_bho_context.py` scores each headword by the share of its corpus
sentences carrying Bhojpuri rather than Hindi grammar; this removes the ones
that fall below --ratio-min.

Two guards keep it from deleting on noise:

  attestation  a headword any Bhojpuri-asserting source lists is never touched,
               whatever the corpus says about it.
  support      a headword scored on fewer than --support-min marked lines is
               kept: one Hindi-looking sentence is not evidence. कऊआ "crow" is
               attested Bhojpuri and scores 0.0 on a single line.

Read the threshold against the corpus baseline, not against 1.0: the Bhojpuri
corpus is itself about 91% Bhojpuri-marked, so 0.91 is an average word, not a
suspicious one. A threshold near the baseline removes ordinary vocabulary —
माटी "clay" scores 0.888 over 2,616 lines. That is a lexicographic choice, not
a data-quality one, so it lives behind a flag rather than in `make triage`.

Usage
    python3 pipeline/drop_shared_vocabulary.py                    # report only
    python3 pipeline/drop_shared_vocabulary.py --apply
    python3 pipeline/drop_shared_vocabulary.py --ratio-min 0.75 --apply
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANON = ROOT / "data" / "canonical"
CLEAN = ROOT / "data" / "cleaning"
SCORES = CLEAN / "context-scores.jsonl"

# The dictionary files, in the order `make data` reads them (the -review holding
# files are not part of the dictionary and are left alone).
FILES = ["wiktionary-bho", "wiktionary-translations-bho", "gatitos-bho",
         "hindi-cognates-bho", "aligned-bho", "langlinks-bho", "community-bho"]

# Sources that assert "this word is Bhojpuri" rather than inferring it.
ATTESTING = {"wiktionary-bho", "gatitos-bho", "wiktionary-translations-bho", "community-bho"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="rewrite the canonical files")
    ap.add_argument("--ratio-min", type=float, default=0.9,
                    help="drop below this bho_ratio (corpus baseline is ~0.91)")
    ap.add_argument("--support-min", type=int, default=10,
                    help="ignore headwords scored on fewer marked lines than this")
    args = ap.parse_args()

    if not SCORES.exists():
        sys.exit(f"{SCORES} missing — run `make triage` (needs the corpus)")
    scores = {}
    for line in SCORES.open(encoding="utf-8"):
        if line.strip():
            d = json.loads(line)
            scores[d["word"]] = d

    entries: dict[str, list] = defaultdict(list)
    sources: dict[str, set] = defaultdict(set)
    for name in FILES:
        path = CANON / f"{name}.jsonl"
        if not path.exists():
            continue
        with path.open() as fh:
            for line in fh:
                if line.strip():
                    e = json.loads(line)
                    entries[name].append(e)
                    sources[e["word"]].add(name)

    drop, spared = set(), Counter()
    for word, srcs in sources.items():
        if srcs & ATTESTING:
            spared["attested by a Bhojpuri source"] += 1
            continue
        sc = scores.get(word)
        if not sc or sc.get("bho_ratio") is None:
            spared["no corpus score"] += 1
            continue
        if sc["support"] < args.support_min:
            spared[f"under {args.support_min} marked lines"] += 1
            continue
        if sc["bho_ratio"] < args.ratio_min:
            drop.add(word)

    log = []
    for name, rows in entries.items():
        for e in rows:
            if e["word"] in drop:
                sc = scores[e["word"]]
                log.append({
                    "id": f"{name}:{e['word']}", "word": e["word"], "file": f"{name}.jsonl",
                    "bho_ratio": sc["bho_ratio"], "support": sc["support"],
                    "gloss": ((e.get("senses") or [{}])[0].get("gloss") or "")[:100],
                })

    total = sum(len(v) for v in entries.values())
    print(f"bho_ratio < {args.ratio_min} on >= {args.support_min} marked lines, "
          f"no Bhojpuri-asserting source")
    print(f"  {len(drop)} headwords / {len(log)} entries of {len(sources)} / {total}")
    for why, n in spared.most_common():
        print(f"  kept {n:6}  {why}")
    print("\nlowest-scoring:")
    for d in sorted(log, key=lambda d: d["bho_ratio"])[:10]:
        print(f"   {d['word']:12} {d['bho_ratio']:<7} {d['support']:<6} {d['gloss'][:40]}")

    if not args.apply:
        print("\nreport only. pass --apply to write", file=sys.stderr)
        return

    CLEAN.mkdir(parents=True, exist_ok=True)
    out = CLEAN / "shared-below-ratio.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for d in log:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")

    for name, rows in entries.items():
        keep = [e for e in rows if e["word"] not in drop]
        if len(keep) == len(rows):
            continue
        with (CANON / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for e in keep:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        print(f"  {name:32} -{len(rows) - len(keep)} of {len(rows)}", file=sys.stderr)
    print(f"logged {len(log)} removals in {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
