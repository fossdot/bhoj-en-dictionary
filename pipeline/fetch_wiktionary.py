#!/usr/bin/env python3
"""Fetch all Bhojpuri lemmas from English Wiktionary via the MediaWiki API
and emit canonical JSONL entries (data/canonical/wiktionary-bho.jsonl).

English Wiktionary content is CC BY-SA 4.0. Each emitted entry records its
source page URL for attribution.

Usage:
    python3 pipeline/fetch_wiktionary.py
"""

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://en.wiktionary.org/w/api.php"
UA = "bhoj-dictionary-pipeline/0.1 (vishal@fossunited.org)"
OUT = Path(__file__).resolve().parent.parent / "data" / "canonical" / "wiktionary-bho.jsonl"
RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "wiktionary"

# Part-of-speech section headers used by English Wiktionary that we map to
# dictpress-style type slugs.
POS_MAP = {
    "Noun": "noun",
    "Proper noun": "propernoun",
    "Verb": "verb",
    "Adjective": "adjective",
    "Adverb": "adverb",
    "Pronoun": "pronoun",
    "Conjunction": "conjunction",
    "Postposition": "postposition",
    "Preposition": "preposition",
    "Interjection": "interjection",
    "Numeral": "numeral",
    "Determiner": "determiner",
    "Particle": "particle",
    "Classifier": "classifier",
    "Phrase": "phrase",
    "Proverb": "proverb",
    "Suffix": "suffix",
    "Prefix": "prefix",
}


def api_get(params: dict) -> dict:
    params = {**params, "format": "json", "formatversion": "2"}
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def category_members(category: str) -> list[str]:
    """All page titles in a category, following pagination."""
    titles, cont = [], {}
    while True:
        data = api_get({
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmlimit": "500",
            "cmnamespace": "0",  # main namespace only (skip subcategory pages)
            **cont,
        })
        titles += [m["title"] for m in data["query"]["categorymembers"]]
        if "continue" not in data:
            return titles
        cont = data["continue"]


def fetch_wikitext(titles: list[str]) -> dict[str, str]:
    """Fetch raw wikitext for up to 50 titles per request."""
    out = {}
    for i in range(0, len(titles), 50):
        batch = titles[i : i + 50]
        data = api_get({
            "action": "query",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "titles": "|".join(batch),
        })
        for page in data["query"]["pages"]:
            if "revisions" in page:
                out[page["title"]] = page["revisions"][0]["slots"]["main"]["content"]
        time.sleep(0.5)  # be polite
        print(f"  fetched {min(i + 50, len(titles))}/{len(titles)} pages", file=sys.stderr)
    return out


def extract_language_section(wikitext: str, lang: str = "Bhojpuri") -> str | None:
    """Return the L2 section for `lang` from a Wiktionary page."""
    m = re.search(rf"^==\s*{lang}\s*==\s*$(.*?)(?=^==[^=]|\Z)", wikitext, re.M | re.S)
    return m.group(1) if m else None


TEMPLATE_RE = re.compile(r"\{\{([^{}]*(?:\{\{[^{}]*\}\}[^{}]*)*)\}\}")
LINK_RE = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]")


def strip_wiki_markup(text: str) -> str:
    """Best-effort conversion of a definition line's wikitext to plain text."""

    def template_to_text(m: re.Match) -> str:
        parts = m.group(1).split("|")
        name = parts[0].strip().lower()
        args = [p for p in parts[1:] if "=" not in p]
        if name in ("l", "link", "m", "mention") and len(args) >= 2:
            return args[1]
        if name in ("gloss", "gl", "qualifier", "q", "i", "lb", "lbl", "label"):
            # {{lb|bho|dialect}} → (dialect); drop the lang-code arg
            inner = ", ".join(a for a in args if a not in ("bho", "en"))
            return f"({inner})" if inner else ""
        if name in ("w",) and args:
            return args[-1]
        if name in ("alternative form of", "alt form", "altform", "alternative spelling of", "alt sp") and len(args) >= 2:
            return f"alternative form of {args[1]}"
        if name in ("synonym of", "syn of") and len(args) >= 2:
            return f"synonym of {args[1]}"
        if name in ("non-gloss", "non-gloss definition", "n-g", "ngd") and args:
            return args[0]
        if name in ("bho-sc", "mag-sc") and args:
            # cross-script counterpart: Kaithi page pointing at Devanagari form (or vice versa)
            return f"script variant of {args[0]}"
        if name == "spelling of" and len(args) >= 3:
            return f"{args[1]} spelling of {args[2]}"
        if name in ("tcl", "tcx") and len(args) >= 2:  # translation-hub link: {{tcl|bho|Delhi|...}}
            return args[1]
        if name == "place" and len(args) >= 2:
            kw = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
            names = [v for k, v in sorted(kw.items()) if k.startswith("t")]
            return "; ".join(names) if names else args[1]
        return ""

    prev = None
    while prev != text:  # templates can nest
        prev = text
        text = TEMPLATE_RE.sub(template_to_text, text)
    text = LINK_RE.sub(r"\1", text)
    text = text.replace("'''", "").replace("''", "")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip(" .;,")
    return text


def parse_head_templates(section: str) -> tuple[list[str], list[str]]:
    """Pull transliterations and IPA from headword/pronunciation templates."""
    translits, phones = [], []
    for m in TEMPLATE_RE.finditer(section):
        parts = m.group(1).split("|")
        name = parts[0].strip().lower()
        kwargs = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
        if name.startswith("bho-") or name in ("head",):
            for key in ("tr", "tr1"):
                if kwargs.get(key):
                    translits.append(kwargs[key])
        if name in ("ipa", "bho-ipa"):
            phones += [p for p in parts[1:] if "=" not in p and p != "bho"]
    return list(dict.fromkeys(translits)), list(dict.fromkeys(phones))


def parse_example(line: str) -> dict | None:
    """Parse a '#:' usage-example line: {{ux|bho|<text>|<translation>|tr=...}}."""
    for m in TEMPLATE_RE.finditer(line):
        parts = m.group(1).split("|")
        name = parts[0].strip().lower()
        if name not in ("ux", "uxi", "usex", "quote", "co", "coi"):
            continue
        args = [p for p in parts[1:] if "=" not in p]
        kwargs = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
        if not args or args[0] != "bho":
            continue
        clean = lambda s: re.sub(r"\s+", " ", LINK_RE.sub(r"\1", s.replace("'''", "").replace("''", ""))).strip()
        ex = {"bho": clean(args[1])} if len(args) >= 2 else None
        if not ex or not ex["bho"]:
            continue
        translation = kwargs.get("t") or (args[2] if len(args) >= 3 else None)
        if translation:
            ex["en"] = clean(translation)
        if kwargs.get("tr"):
            ex["translit"] = clean(kwargs["tr"])
        return ex
    return None


def detect_script(word: str) -> str:
    for ch in word:
        cp = ord(ch)
        if 0x11080 <= cp <= 0x110CF:
            return "Kthi"  # Kaithi
        if 0x0900 <= cp <= 0x097F:
            return "Deva"
    return "Latn"


GENDER_RE = re.compile(r"\{\{bho-(?:noun|proper noun)\|[^}]*g=([mfn])")


def parse_entry(title: str, wikitext: str) -> dict | None:
    section = extract_language_section(wikitext)
    if section is None:
        return None

    translits, phones = parse_head_templates(section)
    senses = []
    current_pos = None
    for line in section.splitlines():
        header = re.match(r"^===+\s*([^=]+?)\s*===+\s*$", line)
        if header:
            current_pos = POS_MAP.get(header.group(1).strip())
            continue
        # definition lines start with single '#' (not #: examples or ## subsenses)
        if re.match(r"^#[^#:*]", line) and current_pos:
            gloss = strip_wiki_markup(line[1:])
            if gloss:
                senses.append({"pos": current_pos, "gloss": gloss, "examples": []})
        # '#:' or '#*' lines attach a usage example to the preceding sense
        elif re.match(r"^#+[:*]", line) and senses:
            ex = parse_example(line)
            if ex:
                senses[-1]["examples"].append(ex)

    if not senses:
        return None
    tags = []
    g = GENDER_RE.search(section)
    if g:
        tags.append(f"gender:{g.group(1)}")
    return {
        "word": title,
        "lang": "bho",
        "script": detect_script(title),
        "translit": translits,
        "phones": phones,
        "tags": tags,
        "senses": senses,  # glosses are English → this is the bho→en direction
        "source": "en.wiktionary.org",
        "source_url": f"https://en.wiktionary.org/wiki/{urllib.parse.quote(title)}#Bhojpuri",
        "license": "CC BY-SA 4.0",
    }


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    cache = RAW / "pages.json"
    if cache.exists() and "--refresh" not in sys.argv:
        print(f"Using cached pages from {cache} (pass --refresh to refetch)", file=sys.stderr)
        pages = json.loads(cache.read_text())
    else:
        print("Listing Category:Bhojpuri lemmas …", file=sys.stderr)
        titles = sorted(set(category_members("Category:Bhojpuri lemmas")))
        print(f"  {len(titles)} lemma pages", file=sys.stderr)
        pages = fetch_wikitext(titles)
        cache.write_text(json.dumps(pages, ensure_ascii=False, indent=1))

    entries, skipped = [], []
    for title, text in sorted(pages.items()):
        entry = parse_entry(title, text)
        if entry:
            entries.append(entry)
        else:
            skipped.append(title)

    with OUT.open("w") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    print(f"Wrote {len(entries)} entries → {OUT}", file=sys.stderr)
    if skipped:
        print(f"Skipped {len(skipped)} pages with no parseable senses: {skipped[:10]} …", file=sys.stderr)


if __name__ == "__main__":
    main()
