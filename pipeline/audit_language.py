#!/usr/bin/env python3
"""Heuristic Bhojpuri-vs-Hindi audit of the mono corpus.

Web crawls labeled `bho` routinely contain Hindi. This scores every line by
counting distinctive function words / auxiliaries:

  Bhojpuri markers: बा बाड़े बानी बाटे बहे भइल गइल रहल करेला होला खातिर
                     बाड़ी बतावल कइल जाला लोग के बारे में ...
  Hindi markers:     है हैं था थी थे किया गया रहा कर रहे होता चाहिए हुआ

A line with more Hindi than Bhojpuri markers is flagged. Writes
data/corpus/QUALITY.md with per-file percentages.

Usage:
    python3 pipeline/audit_language.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MONO = ROOT / "data" / "corpus" / "mono"

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


def audit(path: Path) -> tuple[int, int, int, int]:
    bho_lines = hi_lines = neutral = total = 0
    for ln in path.open():
        ln = ln.strip()
        if not ln:
            continue
        total += 1
        b, h = len(BHO.findall(ln)), len(HI.findall(ln))
        if b > h:
            bho_lines += 1
        elif h > b:
            hi_lines += 1
        else:
            neutral += 1
    return bho_lines, hi_lines, neutral, total


def main() -> None:
    rows = []
    for path in sorted(MONO.glob("*.txt")):
        if path.name == "bhwiki-titles.txt":
            continue
        b, h, n, t = audit(path)
        if not t:
            continue
        rows.append((path.name, t, 100 * b / t, 100 * h / t, 100 * n / t))
        print(f"  {path.name}: {t} lines — bho {100*b/t:.0f}% | hindi {100*h/t:.0f}% | neutral {100*n/t:.0f}%", file=sys.stderr)

    out = ROOT / "data" / "corpus" / "QUALITY.md"
    lines = [
        "# Language audit (heuristic)",
        "",
        "Marker-word vote per line: bho-markers vs hindi-markers. \"Neutral\" =",
        "tie or no markers (short lines, names, lists). Directional, not exact.",
        "",
        "| file | lines | bho% | hindi% | neutral% |",
        "|---|---:|---:|---:|---:|",
    ]
    lines += [f"| {n} | {t} | {b:.0f} | {h:.0f} | {x:.0f} |" for n, t, b, h, x in rows]
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
