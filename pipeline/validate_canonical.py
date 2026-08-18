#!/usr/bin/env python3
"""Validate data/canonical/*.jsonl against the entry schema.

Run locally or in CI (.github/workflows/validate.yml) so a pull request that
breaks the dictionary data fails before review.

    python3 pipeline/validate_canonical.py

Exit code 1 if any error is found. Warnings do not fail the build.
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANON = ROOT / "data" / "canonical"

REQUIRED = {"word", "lang", "senses", "source", "license"}
POS = {
    "", "noun", "propernoun", "verb", "adjective", "adverb", "pronoun",
    "conjunction", "postposition", "preposition", "interjection", "numeral",
    "determiner", "particle", "classifier", "phrase", "proverb", "suffix", "prefix",
}
SCRIPTS = {"Deva", "Kthi", "Latn"}
DEVA = re.compile(r"[ऀ-ॿ]")
KAITHI = re.compile(r"[\U00011080-\U000110CF]")

errors: list[str] = []
warnings: list[str] = []


def check_file(path: Path) -> int:
    seen: dict[str, int] = {}
    n = 0
    for i, line in enumerate(path.open(), 1):
        line = line.strip()
        if not line:
            continue
        where = f"{path.name}:{i}"
        try:
            e = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{where}: invalid JSON — {exc}")
            continue
        n += 1

        missing = REQUIRED - e.keys()
        if missing:
            errors.append(f"{where}: missing field(s) {sorted(missing)}")
            continue

        word = e["word"]
        if not isinstance(word, str) or not word.strip():
            errors.append(f"{where}: empty word")
            continue
        if word != word.strip():
            errors.append(f"{where}: word has leading/trailing whitespace: {word!r}")
        if unicodedata.normalize("NFC", word) != word:
            errors.append(f"{where}: word is not NFC-normalized: {word!r} (run pipeline/clean_canonical.py)")
        if word in seen:
            errors.append(f"{where}: duplicate word {word!r} (first seen line {seen[word]})")
        seen[word] = i

        if e["lang"] != "bho":
            errors.append(f"{where}: lang must be 'bho', got {e['lang']!r}")

        script = e.get("script")
        if script is not None and script not in SCRIPTS:
            errors.append(f"{where}: script must be one of {sorted(SCRIPTS)}, got {script!r}")
        if script == "Deva" and not DEVA.search(word):
            errors.append(f"{where}: script=Deva but no Devanagari in {word!r}")
        if script == "Kthi" and not KAITHI.search(word):
            errors.append(f"{where}: script=Kthi but no Kaithi in {word!r}")

        senses = e["senses"]
        if not isinstance(senses, list) or not senses:
            errors.append(f"{where}: {word!r} has no senses")
            continue
        for j, s in enumerate(senses):
            if not isinstance(s, dict) or "gloss" not in s:
                errors.append(f"{where}: {word!r} sense {j} is malformed")
                continue
            gloss = s["gloss"]
            if not isinstance(gloss, str) or not gloss.strip():
                errors.append(f"{where}: {word!r} sense {j} has an empty gloss")
            elif DEVA.search(gloss) and "variant of" not in gloss and "spelling of" not in gloss:
                warnings.append(f"{where}: {word!r} sense {j} gloss contains Devanagari (should be English): {gloss[:50]!r}")
            if re.search(r"\[\[|\{\{|<[a-z/]", str(gloss)):
                errors.append(f"{where}: {word!r} sense {j} gloss contains markup: {gloss[:50]!r}")
            if s.get("pos", "") not in POS:
                errors.append(f"{where}: {word!r} sense {j} has unknown pos {s.get('pos')!r}")
            for ex in s.get("examples", []) or []:
                if not ex.get("bho"):
                    errors.append(f"{where}: {word!r} sense {j} has an example with no 'bho' text")
    return n


def main() -> None:
    files = sorted(p for p in CANON.glob("*.jsonl") if not p.name.endswith("-review.jsonl"))
    if not files:
        sys.exit("no canonical files found")
    total = 0
    for p in files:
        n = check_file(p)
        total += n
        print(f"  {p.name}: {n} entries")
    print(f"\n{total} entries checked across {len(files)} files")
    for w in warnings[:20]:
        print(f"WARN  {w}")
    if len(warnings) > 20:
        print(f"... and {len(warnings) - 20} more warnings")
    for e in errors[:40]:
        print(f"ERROR {e}")
    if len(errors) > 40:
        print(f"... and {len(errors) - 40} more errors")
    if errors:
        sys.exit(f"\n{len(errors)} error(s) — see above")
    print(f"OK ({len(warnings)} warnings)")


if __name__ == "__main__":
    main()
