#!/usr/bin/env python3
"""Attach usage examples to headwords from the parallel corpora.

The dictionary had 33 usage examples against 13,473 headwords, while
176k bho-en sentence pairs sat unused in data/corpus/parallel/. Examples
are the highest-value content here twice over: a reader learns more from
one sentence than from three glosses, and parallel text is the only thing
that actually teaches a model the language.

Licensing decides what may be attached to what. Entries are CC BY-SA 4.0
or CC BY 4.0, and a share-alike example would impose share-alike on an
entry that does not carry it, so SA sentences go only onto SA entries.
Permissive sentences go anywhere. Every example records its own source
and licence.

BHLTR is excluded entirely: CC-BY-NC-SA would make the dictionary
non-commercial. FLORES and the other EVAL-ONLY sets are excluded so the
benchmark stays clean.

Usage:
    python3 pipeline/mine_examples.py            # report only
    python3 pipeline/mine_examples.py --apply
"""

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANON = ROOT / "data" / "canonical"
PAR = ROOT / "data" / "corpus" / "parallel"

# rank: professional translation first, then community, then mined.
SOURCES = [
    ("nllb-seed.jsonl",            "NLLB-Seed",          "CC BY-SA 4.0", "sa", 0),
    ("nllb-md-chat-train.jsonl",   "NLLB-MD (chat)",     "CC BY-SA 4.0", "sa", 0),
    ("nllb-md-health-train.jsonl", "NLLB-MD (health)",   "CC BY-SA 4.0", "sa", 0),
    ("nllb-md-news-train.jsonl",   "NLLB-MD (news)",     "CC BY-SA 4.0", "sa", 0),
    ("nllb-md-chat-valid.jsonl",   "NLLB-MD (chat)",     "CC BY-SA 4.0", "sa", 0),
    ("nllb-md-health-valid.jsonl", "NLLB-MD (health)",   "CC BY-SA 4.0", "sa", 0),
    ("nllb-md-news-valid.jsonl",   "NLLB-MD (news)",     "CC BY-SA 4.0", "sa", 0),
    ("tatoeba.jsonl",              "Tatoeba",            "CC BY 2.0 FR", "permissive", 1),
    ("translatewiki.jsonl",        "translatewiki.net",  "CC BY 3.0",    "permissive", 1),
    ("wikimedia.jsonl",            "Wikimedia",          "CC BY-SA 3.0", "sa", 1),
]

DEVA = re.compile(r"[ऀ-ॿ]+")
BAD = re.compile(r"https?://|www\.|[<>{}|@#]|\d{4,}")
MAX_PER_ENTRY = 2
MIN_BHO_TOKENS, MAX_BHO_TOKENS = 4, 18
MIN_EN_WORDS, MAX_EN_WORDS = 3, 28


def nfc(s):
    return unicodedata.normalize("NFC", s)


def usable(bho, en):
    if BAD.search(bho) or BAD.search(en):
        return False
    toks = DEVA.findall(bho)
    if not (MIN_BHO_TOKENS <= len(toks) <= MAX_BHO_TOKENS):
        return False
    words = en.split()
    if not (MIN_EN_WORDS <= len(words) <= MAX_EN_WORDS):
        return False
    # mostly Devanagari on the Bhojpuri side
    deva_chars = sum(len(t) for t in toks)
    return deva_chars >= 0.5 * len(bho.replace(" ", ""))


def load_candidates(headwords):
    """headword -> list of (rank, len, bho, en, source, license, share)."""
    cand = defaultdict(list)
    for fname, label, lic, share, rank in SOURCES:
        p = PAR / fname
        if not p.exists():
            continue
        for line in p.open(encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            bho, en = (d.get("bho") or "").strip(), (d.get("en") or "").strip()
            if not bho or not en or not usable(bho, en):
                continue
            for t in set(DEVA.findall(nfc(bho))):
                if t in headwords:
                    cand[t].append((rank, len(bho), bho, en, label, lic, share))
    return cand


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-per-entry", type=int, default=MAX_PER_ENTRY)
    args = ap.parse_args()

    files = {p: [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]
             for p in sorted(CANON.glob("*.jsonl"))}
    headwords = {nfc(e["word"]) for rows in files.values() for e in rows}
    print(f"loading candidates for {len(headwords)} headwords…", file=sys.stderr)
    cand = load_candidates(headwords)
    print(f"  {len(cand)} headwords have at least one usable sentence", file=sys.stderr)

    n_entries = n_examples = 0
    skipped_license = 0
    for path, rows in files.items():
        for e in rows:
            senses = e.get("senses") or []
            if not senses or any(s.get("examples") for s in senses):
                continue
            w = nfc(e["word"])
            pool = cand.get(w)
            if not pool:
                continue
            entry_sa = "SA" in e.get("license", "").upper().replace("-", "")
            picked, seen = [], set()
            for rank, _, bho, en, label, lic, share in sorted(pool):
                if share == "sa" and not entry_sa:
                    skipped_license += 1
                    continue
                key = bho.strip()
                if key in seen:
                    continue
                seen.add(key)
                picked.append({"bho": bho, "en": en, "source": label, "license": lic})
                if len(picked) >= args.max_per_entry:
                    break
            if picked:
                senses[0].setdefault("examples", [])
                senses[0]["examples"].extend(picked)
                n_entries += 1
                n_examples += len(picked)

    print(f"\nentries gaining examples : {n_entries}")
    print(f"examples attached        : {n_examples}")
    print(f"skipped, licence mismatch: {skipped_license} (share-alike onto a CC BY entry)")

    if not args.apply:
        print("\nreport only; pass --apply to write", file=sys.stderr)
        return

    for path, rows in files.items():
        with path.open("w", encoding="utf-8") as fh:
            for e in rows:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    print("wrote canonical files", file=sys.stderr)


if __name__ == "__main__":
    main()
