#!/usr/bin/env python3
"""Mechanical cleaning pass over data/canonical/*.jsonl — idempotent, in place.

Fixes (each logged to data/cleaning/mechanical-log.jsonl):
  nfc          Unicode-normalize word/translit/glosses to NFC (66 headwords
               existed in both composed and decomposed form → visible dupes)
  dedupe-sense drop senses whose gloss is a normalized duplicate of an
               earlier sense on the same entry (keep the richer gloss)
  crossref     hi-cognates glosses like "nuqtaless form of अंग्रेज़ (aṅgrez)"
               → rewritten to "spelling variant of X" + target's gloss
  paren-word   langlinks headwords like "अखिल (गायक)" → strip the
               disambiguating parenthetical (drop on collision)
  markup       strip residual wiki quotes ''…'' and collapse whitespace

Usage:
    python3 pipeline/clean_canonical.py
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANON = ROOT / "data" / "canonical"
LOG = ROOT / "data" / "cleaning" / "mechanical-log.jsonl"

FILES = [
    "wiktionary-bho", "wiktionary-translations-bho", "gatitos-bho",
    "hindi-cognates-bho", "aligned-bho", "langlinks-bho", "community-bho",
]

FORM_OF_RE = re.compile(r"\bform of ([ऀ-ॿ़]+)")
PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")

log_entries = []


def log(kind: str, file: str, word: str, detail: str) -> None:
    log_entries.append({"fix": kind, "file": file, "word": word, "detail": detail})


def norm_gloss_key(g: str) -> str:
    return re.sub(r"\s*\([^)]*\)", "", g).lower().strip(" .,;")


def clean_text(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = s.replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", s).strip()


def clean_file(name: str, gloss_index: dict[str, str]) -> None:
    path = CANON / f"{name}.jsonl"
    entries = [json.loads(l) for l in path.open()]
    out = []
    seen_words: set[str] = set()

    for e in entries:
        word = unicodedata.normalize("NFC", e["word"]).strip()
        if word != e["word"]:
            log("nfc", name, e["word"], f"→ {word}")
        e["word"] = word
        e["translit"] = [unicodedata.normalize("NFC", t) for t in e.get("translit", [])]

        # langlinks: strip disambiguating parenthetical from the headword
        if name == "langlinks-bho" and PAREN_RE.search(word):
            stripped = PAREN_RE.sub("", word).strip()
            if stripped and re.search(r"[ऀ-ॿ]", stripped):
                log("paren-word", name, word, f"→ {stripped}")
                e["word"] = word = stripped

        if word in seen_words:
            log("dupe-entry", name, word, "dropped later duplicate within file")
            continue
        seen_words.add(word)

        senses, keys = [], {}
        for s in e["senses"]:
            g = clean_text(s["gloss"])
            # hi-cognates cross-reference glosses pointing at another Devanagari form
            if name == "hindi-cognates-bho" and re.search(r"[ऀ-ॿ]", g):
                m = FORM_OF_RE.search(g)
                if m:
                    target = m.group(1)
                    tgloss = gloss_index.get(unicodedata.normalize("NFC", target), "")
                    new = f"spelling variant of {target}" + (f": {tgloss}" if tgloss else "")
                    log("crossref", name, word, f"{g[:60]} → {new[:60]}")
                    g = new
            if g != s["gloss"]:
                if "form of" not in g and g != clean_text(s["gloss"]):
                    pass  # already logged as crossref
                elif g != unicodedata.normalize("NFC", s["gloss"]).strip():
                    log("markup", name, word, s["gloss"][:60])
            s["gloss"] = g
            key = norm_gloss_key(g)
            if key in keys:
                # keep whichever gloss is richer (longer)
                if len(g) > len(senses[keys[key]]["gloss"]):
                    senses[keys[key]]["gloss"] = g
                    senses[keys[key]]["examples"] = senses[keys[key]]["examples"] or s.get("examples", [])
                log("dedupe-sense", name, word, g[:60])
                continue
            keys[key] = len(senses)
            senses.append(s)
        e["senses"] = senses
        if not senses:
            log("empty-entry", name, word, "no senses left; dropped")
            continue
        out.append(e)

    with path.open("w") as f:
        for e in out:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"  {name}: {len(entries)} → {len(out)} entries", file=sys.stderr)


def main() -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)

    # index: NFC word → first gloss, for resolving cross-references
    gloss_index: dict[str, str] = {}
    for name in FILES:
        for line in (CANON / f"{name}.jsonl").open():
            e = json.loads(line)
            w = unicodedata.normalize("NFC", e["word"])
            if w not in gloss_index and e["senses"]:
                g = e["senses"][0]["gloss"]
                if not re.search(r"[ऀ-ॿ]", g):  # don't index cross-refs themselves
                    gloss_index[w] = g

    for name in FILES:
        clean_file(name, gloss_index)

    if log_entries:  # never clobber a previous run's log with an empty pass
        with LOG.open("w") as f:
            for row in log_entries:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    from collections import Counter
    counts = Counter(r["fix"] for r in log_entries)
    print(f"fixes: {dict(counts)} → {LOG}", file=sys.stderr)


if __name__ == "__main__":
    main()
