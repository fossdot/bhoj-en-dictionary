#!/usr/bin/env python3
"""Score a headword by how Bhojpuri the sentences it appears in are.

Corpus frequency alone cannot tell a Bhojpuri word from a Hindi one: the
`bho` corpus is a few percent Hindi, and the two languages share most of
their lexicon anyway. Context can. A word that belongs to Bhojpuri turns
up in sentences carrying Bhojpuri auxiliaries (बा, भइल, खातिर); a Hindi
intruder drags its own grammar in with it (है, था, किया).

For every candidate headword this counts the lines it occurs in that are
Bhojpuri-marked vs Hindi-marked, and reports

    bho_ratio = bho_lines / (bho_lines + hi_lines)

Controls are scored alongside the candidates so the separation can be
checked rather than assumed: known Bhojpuri lemmas should sit high, Hindi
function words low.

Usage:
    python3 pipeline/score_bho_context.py
"""

import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANON = ROOT / "data" / "canonical"
CORPUS = ROOT / "data" / "corpus" / "mono" / "all-dedup-lid-bho.txt"
OUT = ROOT / "data" / "cleaning" / "context-scores.jsonl"

BHO = re.compile(
    r"(?<![ऀ-ॿ])(बा|बाटे|बाड़े|बाड़ें|बानी|बिया|बाड़ी|भइल|गइल|रहल|कइल|"
    r"होला|जाला|करेला|खातिर|आपन|ओकर|एकर|इहाँ|उहाँ|कवनो|बहुते|लोगन|"
    r"होखे|करीं|बतवलें|कहलें|दिहल|लिहल|अइसन|जइसन|ओइसन|कइसन)(?![ऀ-ॿ])"
)
HI = re.compile(
    r"(?<![ऀ-ॿ])(है|हैं|था|थी|थे|किया|गया|गयी|गई|रहा|रही|रहे|हुआ|हुई|हुए|"
    r"होता|होती|होते|करना|करने|चाहिए|इसका|उसका|इसके|उसके|यहाँ|वहाँ|"
    r"कोई|अपना|अपने|लेकिन|इसलिए|क्योंकि)(?![ऀ-ॿ])"
)
TOKEN = re.compile(r"[ऀ-ॿ]+")

# Marker words would score themselves; never report on them.
MARKERS = set(BHO.pattern.replace("(?<![ऀ-ॿ])(", "").replace(")(?![ऀ-ॿ])", "").split("|")) | \
          set(HI.pattern.replace("(?<![ऀ-ॿ])(", "").replace(")(?![ऀ-ॿ])", "").split("|"))

CONTROL_HI = ["है", "हैं", "था", "किया", "गया", "रहा", "लेकिन", "क्योंकि", "उसका", "चाहिए"]


def nfc(s):
    return unicodedata.normalize("NFC", s)


def load_candidates():
    """word -> set of tiers it appears under, from the triage output."""
    tiers = defaultdict(set)
    triage = ROOT / "data" / "cleaning" / "triage.jsonl"
    for line in triage.open(encoding="utf-8"):
        d = json.loads(line)
        tiers[nfc(d["word"])].add(d["tier"])
    return tiers


def main():
    tiers = load_candidates()
    # Score every single-token headword, plus the Hindi controls.
    targets = {w for w in tiers if " " not in w and TOKEN.fullmatch(w)}
    targets |= set(CONTROL_HI)
    print(f"scoring {len(targets)} headwords over {CORPUS.name}", file=sys.stderr)

    bho_hits = Counter()
    hi_hits = Counter()
    total_hits = Counter()
    n_bho = n_hi = n_neu = 0

    with CORPUS.open(encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if i and i % 100000 == 0:
                print(f"  {i} lines", file=sys.stderr)
            b, h = len(BHO.findall(line)), len(HI.findall(line))
            if b > h:
                kind, _ = "b", (n_bho := n_bho + 1)
            elif h > b:
                kind, _ = "h", (n_hi := n_hi + 1)
            else:
                kind, _ = "n", (n_neu := n_neu + 1)
            seen = {t for t in TOKEN.findall(nfc(line)) if t in targets}
            for t in seen:
                total_hits[t] += 1
                if kind == "b":
                    bho_hits[t] += 1
                elif kind == "h":
                    hi_hits[t] += 1

    print(f"corpus lines: bho-marked {n_bho}, hindi-marked {n_hi}, neutral {n_neu}",
          file=sys.stderr)
    baseline = n_bho / (n_bho + n_hi)
    print(f"corpus baseline bho_ratio = {baseline:.3f}", file=sys.stderr)

    with OUT.open("w", encoding="utf-8") as out:
        for w in sorted(targets):
            b, h, t = bho_hits[w], hi_hits[w], total_hits[w]
            support = b + h
            ratio = (b / support) if support else None
            out.write(json.dumps({
                "word": w,
                "tiers": sorted(tiers.get(w, ["<control>"])),
                "lines": t, "bho_lines": b, "hi_lines": h,
                "support": support,
                "bho_ratio": round(ratio, 4) if ratio is not None else None,
                "is_marker": w in MARKERS,
            }, ensure_ascii=False) + "\n")

    print(f"wrote {OUT}", file=sys.stderr)
    print(json.dumps({"baseline_bho_ratio": round(baseline, 4),
                      "lines_bho": n_bho, "lines_hi": n_hi, "lines_neutral": n_neu}))


if __name__ == "__main__":
    main()
