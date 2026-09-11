#!/usr/bin/env python3
"""Repair glosses that leaked Devanagari into the English side.

Glosses harvested from Hindi Wiktionary carry the source's own internal
cross-references: "spelling variant of ख़बर: news", "paper; document
(spelling variant of काग़ज़)", "synonym of असली (aslī)". An English reader
gets nothing from the Devanagari half, and on the training side it teaches
a model to emit Devanagari where English was asked for.

Three outcomes, in order of preference:

  strip    the gloss already contains an English definition; the
           cross-reference is removed and the definition kept.
  resolve  the gloss is nothing but a pointer at another headword. If that
           headword is in our own data with an English gloss, inline it and
           record the pointer in tags (see-also:X).
  drop     a pointer we cannot resolve. The sense goes; if it was the only
           sense, the entry goes.

Glosses *about* script — letters, ligatures, diacritics, musical notation,
grammatical frames carrying a real example — keep their Devanagari, which
is the content rather than a leak.

Usage:
    python3 pipeline/fix_glosses.py            # report only
    python3 pipeline/fix_glosses.py --apply
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

DEVA = re.compile(r"[ऀ-ॿ\U00011080-\U000110CF]")

# Glosses whose subject *is* the script or notation: the Devanagari is the
# definition, not a leaked cross-reference.
META = re.compile(
    r"\b(letter|ligature|diacritic|anusvara|avagraha|visarga|halant|virama|"
    r"nuqta|matra|denoted|symbol|Devanagari|Brahmic|script|solfege|raga|"
    r"thaat|prahara|tala|note of|inherent vowel|ezafe|overdot|terminal h)\b",
    re.I,
)

# A pointer with the target's English carried along in parens or after a colon:
#   "synonym of कविता (kavitā, “story, tale; poem”)"  -> story, tale; poem
#   "synonym of स्थलीय (sthalīya): terrestrial"       -> terrestrial
POINTER_WITH_QUOTED = re.compile(
    r"^\s*(?:[Ss]ynonym|[Aa]lternative form|[Nn]uqtaless form|[Ss]pelling variant|"
    r"[Ss]cript variant|[Vv]ariant|[Ee]llipsis)\s+of\s+[^(]*\([^,]*,\s*[“\"](?P<en>[^”\"]+)[”\"]\s*\)\s*$"
)
POINTER_WITH_COLON = re.compile(
    r"^\s*(?:[Ss]ynonym|[Aa]lternative form|[Nn]uqtaless form|[Ss]pelling variant|"
    r"[Ss]cript variant|[Vv]ariant|[Ee]llipsis)\s+of\s+[^:]*:\s*(?P<en>.+)$"
)

# A bare pointer, no English anywhere: "nuqtaless form of अफ़साना (afsānā)"
BARE_POINTER = re.compile(
    r"^\s*(?:[Ss]ynonym|[Aa]lternative form|[Nn]uqtaless form|[Ss]pelling variant|"
    r"[Ss]cript variant|[Kk]aithi spelling|[Bb]raj Bhāshā form|[Cc]onjunctive|"
    r"[Ee]llipsis|[Vv]ariant)\s+of\s+(?P<target>[^\s,(:]+)"
    r"(?:\s*\([^)]*\))?\s*[.;]?\s*$"
)

# Trailing/embedded reference in parentheses next to a real definition:
#   "paper; document (spelling variant of काग़ज़)" -> paper; document
PAREN_REF = re.compile(
    r"\s*\((?:cf\.|see|also|synonym of|spelling variant of|variant of|"
    r"alternative form of|shortened from|feminine of|from)\s+[^)]*\)",
    re.I,
)


def nfc(s):
    return unicodedata.normalize("NFC", s)


def load():
    files = {}
    for p in sorted(CANON.glob("*.jsonl")):
        files[p] = [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]
    return files


def build_index(files):
    """headword -> English glosses that are clean already."""
    idx = defaultdict(list)
    for rows in files.values():
        for e in rows:
            for s in e.get("senses", []):
                g = (s.get("gloss") or "").strip()
                if g and not DEVA.search(g):
                    idx[nfc(e["word"])].append(g)
    return idx


def fix_gloss(gloss, idx):
    """-> (new_gloss|None, action, note). None means drop the sense."""
    g = gloss.strip()
    if not DEVA.search(g):
        return g, "clean", ""
    if META.search(g):
        return g, "keep-meta", ""

    for pat in (POINTER_WITH_QUOTED, POINTER_WITH_COLON):
        m = pat.match(g)
        if m:
            en = m.group("en").strip(" .;")
            if en and not DEVA.search(en):
                return en, "strip", ""

    m = BARE_POINTER.match(g)
    if m:
        target = nfc(m.group("target").strip(" .,;:"))
        hits = idx.get(target)
        if hits:
            return hits[0], "resolve", target
        return None, "drop", target

    # A real definition with a parenthetical reference hanging off it.
    stripped = PAREN_REF.sub("", g).strip(" .,;:")
    if stripped and not DEVA.search(stripped):
        return stripped, "strip", ""

    # "synonym of पीड़ा (pīṛā); pain, suffering" -> pain, suffering
    if ";" in g:
        head, _, tail = g.partition(";")
        if BARE_POINTER.match(head.strip()) and tail.strip() and not DEVA.search(tail):
            return tail.strip(" .;"), "strip", ""

    # "this (proximal demonstrative, variant of ई)" -> this (proximal demonstrative)
    inner = re.sub(r",\s*(?:variant|synonym|spelling variant|alternative form)\s+of\s+[^)]*(?=\))",
                   "", g)
    if inner != g and not DEVA.search(inner):
        return inner.strip(" .,;:"), "strip", ""

    # Definition followed by a colon-introduced reference, or vice versa.
    if ":" in g:
        head, _, tail = g.partition(":")
        if tail.strip() and not DEVA.search(tail):
            return tail.strip(" .;"), "strip", ""
        if head.strip() and not DEVA.search(head):
            return head.strip(" .;"), "strip", ""

    return g, "unhandled", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    files = load()
    idx = build_index(files)
    stats = Counter()
    changes, unhandled, dropped_entries = [], [], []

    for path, rows in files.items():
        keep_rows = []
        for e in rows:
            new_senses = []
            for s in e.get("senses", []):
                before = (s.get("gloss") or "").strip()
                after, action, note = fix_gloss(before, idx)
                stats[action] += 1
                if action == "clean":
                    new_senses.append(s)
                    continue
                if after is None:
                    changes.append((path.name, e["word"], before, "<sense dropped>", action))
                    continue
                if after != before:
                    s = {**s, "gloss": after}
                    changes.append((path.name, e["word"], before, after, action))
                    if action == "resolve":
                        tags = list(s.get("tags", []) or e.get("tags", []) or [])
                        e.setdefault("tags", [])
                        tag = f"see-also:{note}"
                        if tag not in e["tags"]:
                            e["tags"].append(tag)
                if action == "unhandled":
                    unhandled.append((path.name, e["word"], before))
                new_senses.append(s)

            if not new_senses:
                dropped_entries.append((path.name, e["word"]))
                continue
            e["senses"] = new_senses
            keep_rows.append(e)
        files[path] = keep_rows

    print(f"{'strip':>12}  {stats['strip']:4}  cross-reference removed, definition kept")
    print(f"{'resolve':>12}  {stats['resolve']:4}  pointer resolved against our own data")
    print(f"{'drop':>12}  {stats['drop']:4}  unresolvable pointer, sense removed")
    print(f"{'keep-meta':>12}  {stats['keep-meta']:4}  gloss is about the script itself")
    print(f"{'unhandled':>12}  {stats['unhandled']:4}  left alone")
    print(f"{'entries lost':>12}  {len(dropped_entries):4}  (had no sense left)")

    if unhandled:
        print("\nunhandled:")
        for f, w, g in unhandled[:15]:
            print(f"  {w:14} {g[:70]}")

    if not args.apply:
        print("\nreport only; pass --apply to write", file=sys.stderr)
        return

    for path, rows in files.items():
        with path.open("w", encoding="utf-8") as fh:
            for e in rows:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    with (CLEAN / "gloss-fixes.jsonl").open("w", encoding="utf-8") as fh:
        for f, w, b, a, act in changes:
            fh.write(json.dumps({"file": f, "word": w, "action": act,
                                 "before": b, "after": a}, ensure_ascii=False) + "\n")
    print(f"\nwrote canonical files + {CLEAN/'gloss-fixes.jsonl'}", file=sys.stderr)


if __name__ == "__main__":
    main()
