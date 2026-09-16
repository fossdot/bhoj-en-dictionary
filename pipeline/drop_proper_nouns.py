#!/usr/bin/env python3
"""Drop proper nouns — places, people, organisations, festivals — from canonical.

Reviewers kept meeting encyclopedia material in their batches: माले "Malé (the
capital of the Maldives)", लॉयड "Lloyd", अयोध्या "Ayodhya (Ancient city in
India)". A Bhojpuri speaker cannot usefully say whether a city name is "correct
Bhojpuri", so these burn review time that belongs to the vocabulary.

Two signals, because the sources disagree about how much they annotate:

  pos-tagged   en-Wiktionary marks the sense `propernoun`. Exact, no guessing.
  case-tested  The alignment data carries no part of speech, so a single-word
               capitalised gloss is tested against the English side of the
               parallel corpus: how often does this word appear capitalised
               *mid-sentence* versus lowercase anywhere? "Lloyd" is 42:2 and a
               name; "hello" is 4:26 and a word. Sentence-initial capitals are
               not evidence and are ignored.

Capitalisation alone would delete real vocabulary, so KEEP_CAPITALISED holds the
words English capitalises by convention: languages (Spanish, Sanskrit), the
demonyms beside them (Afghan, American), religious adherents (Hindu, Muslim),
weekdays, months, and acronyms that are ordinary words (TV, DNA). Religious
*names* — Holi, Eid, Krishna — are proper nouns and go.

Usage
    python3 pipeline/drop_proper_nouns.py            # report only
    python3 pipeline/drop_proper_nouns.py --apply    # rewrite canonical
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANON = ROOT / "data" / "canonical"
PARALLEL = ROOT / "data" / "corpus" / "parallel"
OUT_DIR = ROOT / "data" / "cleaning"
CASE_CACHE = ROOT / "data" / "corpus" / "en-case.json"

# Capitalised in English, but ordinary entries in a Bhojpuri→English dictionary.
KEEP_CAPITALISED = {
    # languages
    "arabic", "basque", "bhojpuri", "celtic", "chinese", "dutch", "english", "french",
    "german", "germanic", "greek", "hebrew", "indonesian", "italian", "japanese",
    "korean", "latin", "persian", "portuguese", "russian", "sanskrit", "spanish",
    "swahili", "swedish", "thai", "tibetan", "turkish",
    # demonyms
    "afghan", "african", "american", "asian", "australian", "british", "european",
    "indian", "mexican", "roman", "scottish", "swiss",
    # religious adherents (the faiths themselves are proper nouns and are dropped)
    "buddhist", "catholic", "christian", "hindu", "islamic", "jain", "jewish", "muslim",
    # calendar
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    # conventional capitals and acronyms that are everyday vocabulary
    "god", "lord", "sun", "earth", "moon",
    "tv", "dna", "rna", "hiv", "ai", "gps", "ceo", "tb", "sars", "cbd",
}

SINGLE_TOKEN = re.compile(r"[A-Za-z'’.-]+")
EN_TOKEN = re.compile(r"[A-Za-z][A-Za-z'’-]*")
SENTENCE_END = (".", "!", "?", '"', ":")

MIN_CAP_HITS = 5        # below this the corpus has too little to say
CAP_RATIO = 0.9         # share of capitalised uses that makes a word a name


def english_case_counts() -> tuple[Counter, Counter]:
    """How often each English word appears capitalised mid-sentence vs lowercase.

    Built from the English side of the parallel corpus, minus the held-out eval
    sets. Cached, because it is a few million tokens and never changes between
    corpus rebuilds. Returns empty counters when the corpus is not present —
    the pos-tagged rule still works without it.
    """
    if CASE_CACHE.exists():
        d = json.loads(CASE_CACHE.read_text())
        return Counter(d["cap"]), Counter(d["lower"])
    if not PARALLEL.exists():
        return Counter(), Counter()
    cap: Counter = Counter()
    lower: Counter = Counter()
    for path in sorted(PARALLEL.glob("*.jsonl")):
        if "EVAL-ONLY" in path.name:
            continue
        with path.open() as fh:
            for line in fh:
                if not line.strip():
                    continue
                en = json.loads(line).get("en") or ""
                for m in EN_TOKEN.finditer(en):
                    tok = m.group(0)
                    if tok[:1].isupper():
                        before = en[:m.start()].rstrip()
                        if before and not before.endswith(SENTENCE_END):
                            cap[tok.lower()] += 1
                    else:
                        lower[tok.lower()] += 1
    CASE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CASE_CACHE.write_text(json.dumps({"cap": dict(cap), "lower": dict(lower)}))
    return cap, lower


def verdict(entry: dict, cap: Counter, lower: Counter) -> tuple[bool, str]:
    """(is a proper noun, why). Judged on the first sense, which is the headline."""
    senses = entry.get("senses") or []
    if not senses:
        return False, ""
    sense = senses[0]
    gloss = (sense.get("gloss") or "").strip()
    pos = (sense.get("pos") or "").strip()
    if not gloss:
        return False, ""

    head = gloss.split()[0].strip(".,;()").lower()
    if head in KEEP_CAPITALISED:
        return False, ""

    if pos == "propernoun":
        return True, "en-Wiktionary tags the sense propernoun"

    # Untagged: only judge a bare capitalised single word, never a phrase or a
    # gloss carrying a real definition.
    if pos or not gloss[:1].isupper() or not SINGLE_TOKEN.fullmatch(gloss):
        return False, ""
    key = gloss.lower().strip(".")
    c, lo = cap[key], lower[key]
    if c >= MIN_CAP_HITS and c / (c + lo) >= CAP_RATIO:
        return True, f"corpus: capitalised mid-sentence {c}x, lowercase {lo}x"
    return False, ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="rewrite the canonical files")
    args = ap.parse_args()

    cap, lower = english_case_counts()
    if not cap:
        print("no parallel corpus and no cache: pos-tagged rule only "
              "(run `make data` for the case test)", file=sys.stderr)

    by_file: dict[str, list] = defaultdict(list)
    drops: list[dict] = []
    for path in sorted(CANON.glob("*.jsonl")):
        if path.stem.endswith("-review"):
            continue
        with path.open() as fh:
            for lineno, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                e = json.loads(line)
                is_name, why = verdict(e, cap, lower)
                by_file[path.name].append((e, is_name))
                if is_name:
                    drops.append({
                        "id": f"{path.stem}:{e['word']}", "word": e["word"],
                        "file": path.name, "line": lineno, "why": why,
                        "gloss": (e["senses"][0].get("gloss") or "")[:120],
                    })

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "proper-nouns.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for d in drops:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")

    per_file = Counter(d["file"] for d in drops)
    by_why = Counter("pos-tagged" if d["why"].startswith("en-Wiktionary") else "case-tested"
                     for d in drops)
    total = sum(len(v) for v in by_file.values())
    print(f"{len(drops)} proper nouns in {total} entries  {dict(by_why)}")
    for name, n in per_file.most_common():
        print(f"  {name:38} {n}")
    print("\nexamples:")
    for d in drops[:12]:
        print(f"  {d['word']}  →  {d['gloss'][:46]}   ({d['why']})")

    if not args.apply:
        print(f"\nreport only. wrote {out}", file=sys.stderr)
        return

    for name, rows in by_file.items():
        keep = [e for e, is_name in rows if not is_name]
        if len(keep) == len(rows):
            continue
        with (CANON / name).open("w", encoding="utf-8") as fh:
            for e in keep:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        print(f"  {name:38} -{len(rows) - len(keep)} of {len(rows)}", file=sys.stderr)


if __name__ == "__main__":
    main()
