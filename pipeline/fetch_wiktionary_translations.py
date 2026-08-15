#!/usr/bin/env python3
"""Mine Bhojpuri translations out of English Wiktionary translation tables.

English entries carry translation tables like:

    {{trans-top|liquid H2O}}
    * Bhojpuri: {{t|bho|पानी|n|tr=pānī}}

Each such line yields a bho word glossed by the English headword (+ the
trans-top gloss for sense disambiguation) → entries for the bho→en
dictionary, complementary to fetch_wiktionary.py's lemma pages.

Output: data/canonical/wiktionary-translations-bho.jsonl
Usage:  python3 pipeline/fetch_wiktionary_translations.py [--refresh]
"""

import json
import re
import sys
import urllib.parse
from pathlib import Path

from fetch_wiktionary import (
    RAW, api_get, category_members, detect_script, fetch_wikitext,
)

OUT = Path(__file__).resolve().parent.parent / "data" / "canonical" / "wiktionary-translations-bho.jsonl"
CACHE = RAW / "translation-pages.json"

# * Bhojpuri: {{t|bho|पानी|n|tr=pānī}}, {{t+|bho|...}}, {{tt|bho|...}}
BHO_LINE_RE = re.compile(r"^\*:?\s*Bhojpuri\s*:\s*(.+)$", re.M)
T_TEMPLATE_RE = re.compile(r"\{\{t\+?\|bho\|([^}]+)\}\}|\{\{tt\+?\|bho\|([^}]+)\}\}")
TRANS_TOP_RE = re.compile(r"\{\{trans-top(?:-also)?((?:\|[^}]*)?)\}\}")
POS_HEADER_RE = re.compile(r"^===+\s*([^=]+?)\s*===+\s*$")

POS_MAP = {
    "Noun": "noun", "Proper noun": "propernoun", "Verb": "verb",
    "Adjective": "adjective", "Adverb": "adverb", "Pronoun": "pronoun",
    "Conjunction": "conjunction", "Interjection": "interjection",
    "Numeral": "numeral", "Determiner": "determiner", "Particle": "particle",
    "Postposition": "postposition", "Preposition": "preposition",
    "Phrase": "phrase", "Proverb": "proverb",
}


def parse_translations(title: str, wikitext: str) -> list[dict]:
    """Yield (bho_word, translit, gender, gloss, pos) tuples from one page."""
    # translation tables often live on "<word>/translations" subpages
    title = title.removesuffix("/translations")
    out = []
    current_pos = None
    current_gloss = ""
    for line in wikitext.splitlines():
        h = POS_HEADER_RE.match(line)
        if h:
            pos = POS_MAP.get(h.group(1).strip())
            if pos:
                current_pos = pos
            continue
        tt = TRANS_TOP_RE.search(line)
        if tt:
            # first positional (non key=value) arg is the sense gloss
            args = [a.strip() for a in tt.group(1).split("|") if a.strip() and "=" not in a]
            current_gloss = args[0] if args else ""
            continue
        m = BHO_LINE_RE.match(line)
        if not m:
            continue
        for tm in T_TEMPLATE_RE.finditer(m.group(1)):
            body = tm.group(1) or tm.group(2)
            parts = body.split("|")
            args = [p for p in parts if "=" not in p]
            kwargs = dict(p.split("=", 1) for p in parts if "=" in p)
            if not args:
                continue
            word = args[0].strip()
            if not word or word == "[[]]":
                continue
            gender = next((a for a in args[1:] if a in ("m", "f", "n", "mf", "m-p", "f-p")), "")
            out.append({
                "word": word,
                "translit": kwargs.get("tr", ""),
                "gender": gender[:1] if gender else "",
                "gloss": current_gloss,
                "pos": current_pos or "",
                "en": title,
            })
    return out


def main() -> None:
    if CACHE.exists() and "--refresh" not in sys.argv:
        print(f"Using cached pages from {CACHE}", file=sys.stderr)
        pages = json.loads(CACHE.read_text())
    else:
        print("Listing Category:Terms with Bhojpuri translations …", file=sys.stderr)
        titles = sorted(set(category_members("Category:Terms with Bhojpuri translations")))
        print(f"  {len(titles)} pages", file=sys.stderr)
        pages = fetch_wikitext(titles)
        CACHE.write_text(json.dumps(pages, ensure_ascii=False, indent=1))

    # bho word → accumulated senses (one word can translate many English terms)
    by_word: dict[str, dict] = {}
    n_pairs = 0
    for title, text in sorted(pages.items()):
        for t in parse_translations(title, text):
            n_pairs += 1
            e = by_word.setdefault(t["word"], {
                "word": t["word"],
                "lang": "bho",
                "script": detect_script(t["word"]),
                "translit": [],
                "phones": [],
                "tags": [],
                "senses": [],
                "source": "en.wiktionary.org (translation tables)",
                "source_url": f"https://en.wiktionary.org/wiki/{urllib.parse.quote(t['en'])}",
                "license": "CC BY-SA 4.0",
            })
            if t["translit"] and t["translit"] not in e["translit"]:
                e["translit"].append(t["translit"])
            if t["gender"] and f"gender:{t['gender']}" not in e["tags"]:
                e["tags"].append(f"gender:{t['gender']}")
            gloss = t["en"] + (f" ({t['gloss']})" if t["gloss"] and t["gloss"].lower() != t["en"].lower() else "")
            if not any(s["gloss"] == gloss for s in e["senses"]):
                e["senses"].append({"pos": t["pos"], "gloss": gloss, "examples": []})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        for e in by_word.values():
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"{n_pairs} translation pairs → {len(by_word)} unique bho words → {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
