#!/usr/bin/env python3
"""Harvest Bhojpuri vocabulary from the kaikki.org (wiktextract) Hindi dump
and emit canonical JSONL entries (data/canonical/hindi-cognates-bho.jsonl).

Two harvests, merged into one file:

(a) EXPLICIT DESCENDANTS — Hindi entries whose Descendants section lists a
    Bhojpuri word. These are attested Bhojpuri words; the parent's glosses
    are carried over with a "(cf. Hindi <word>)" suffix. tags: src:hi-descendant

(b) CORPUS-ATTESTED SHARED VOCABULARY — Hindi headwords that also occur
    frequently (>= 20 times) as tokens in the deduplicated, LID-filtered
    Bhojpuri monolingual corpus. Shared Indo-Aryan core vocabulary; the
    Hindi gloss almost always holds for Bhojpuri. tags: src:hi-cognate
    Words with corpus frequency 8-19 go to a separate *-review.jsonl that
    is NOT meant for direct import.

English Wiktionary content is CC BY-SA 4.0.

Usage:
    python3 pipeline/fetch_hindi_cognates.py
"""

import gzip
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DUMP = ROOT / "data" / "raw" / "kaikki-hindi" / "hindi.jsonl.gz"
DUMP_URL = "https://kaikki.org/dictionary/Hindi/kaikki.org-dictionary-Hindi.jsonl.gz"
CORPUS = ROOT / "data" / "corpus" / "mono" / "all-dedup-lid-bho.txt"
OUT = ROOT / "data" / "canonical" / "hindi-cognates-bho.jsonl"
OUT_REVIEW = ROOT / "data" / "canonical" / "hindi-cognates-bho-review.jsonl"
UA = "bhoj-dictionary-pipeline/0.1 (vishal@fossunited.org)"

FREQ_MAIN = 20  # corpus frequency threshold for the main file
FREQ_REVIEW = 8  # 8..19 goes to the review file

# kaikki "pos" value -> dictpress-style type slug (anything else -> "")
POS_MAP = {
    "noun": "noun", "name": "propernoun", "verb": "verb", "adj": "adjective",
    "adv": "adverb", "pron": "pronoun", "conj": "conjunction",
    "postp": "postposition", "prep": "preposition", "intj": "interjection",
    "num": "numeral", "det": "determiner", "particle": "particle",
    "phrase": "phrase", "proverb": "proverb", "suffix": "suffix",
    "prefix": "prefix", "classifier": "classifier",
}

# Sense-level tag substrings that mark inflections / soft redirects.
EXCLUDE_TAG_SUBSTRINGS = ("form-of", "alternative", "romanization", "obsolete")
EXCLUDE_GLOSS_PREFIXES = ("inflection of", "alternative", "spelling of")
# "the first vowel of Hindi, …" — alphabet metadata, not a lexical gloss.
LETTER_GLOSS_RE = re.compile(r"^the [a-z-]+ (vowel|consonant)\b.*\bHindi\b", re.I)

# Hindi-only auxiliaries/participles: these appear in Bhojpuri text only as
# Hindi contamination, never as native Bhojpuri function words.
STOPLIST = set(
    "है हैं था थी थे हूँ हूं हो हों हुआ हुई हुए रहा रही रहे गया गयी गई गए "
    "करता करती करते किया करके जाता जाती जाते सकता सकती सकते चाहिए "
    "होता होती होते कहा दिया लिया लिये किये".split()
)

SOURCE = "en.wiktionary.org (Hindi entry; shared Indo-Aryan vocabulary attested in Bhojpuri corpus)"
LICENSE = "CC BY-SA 4.0"

# Devanagari letters/signs, excluding danda (U+0964-65), digits (U+0966-6F)
# and the abbreviation sign (U+0970), so tokens are word-like.
TOKEN_RE = re.compile(r"[ऀ-ॣॱ-ॿ]+")


def source_url(hindi_word: str) -> str:
    return f"https://en.wiktionary.org/wiki/{urllib.parse.quote(hindi_word)}#Hindi"


def detect_script(word: str) -> str:
    for ch in word:
        cp = ord(ch)
        if 0x11080 <= cp <= 0x110CF:
            return "Kthi"
        if 0x0900 <= cp <= 0x097F:
            return "Deva"
    return "Latn"


def devanagari_dominant(word: str) -> bool:
    deva = sum(1 for ch in word if 0x0900 <= ord(ch) <= 0x097F)
    other = sum(1 for ch in word if ch.isalpha() and not 0x0900 <= ord(ch) <= 0x097F)
    return deva > 0 and deva > other


def ensure_dump() -> None:
    ok = False
    if DUMP.exists():
        try:
            with gzip.open(DUMP, "rb") as f:
                f.read(1024)
            ok = True
        except OSError:
            pass
    if not ok:
        print(f"Downloading {DUMP_URL} …", file=sys.stderr)
        DUMP.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(DUMP_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as resp, DUMP.open("wb") as out:
            while chunk := resp.read(1 << 20):
                out.write(chunk)


def build_freq_table() -> Counter:
    """Devanagari word-token frequencies over the Bhojpuri mono corpus."""
    freq = Counter()
    with CORPUS.open(encoding="utf-8") as f:
        for line in f:
            freq.update(TOKEN_RE.findall(unicodedata.normalize("NFC", line)))
    return freq


def clean_gloss(gloss: str) -> str:
    gloss = re.sub(r"\s+", " ", gloss).strip()
    gloss = gloss.rstrip(".").strip()
    return gloss[:120]


def real_senses(entry: dict) -> list[tuple[str, str]]:
    """(pos_slug, gloss) pairs for an entry, skipping inflections/redirects."""
    pos = POS_MAP.get(entry.get("pos", ""), "")
    out = []
    for sense in entry.get("senses", []):
        if sense.get("form_of") or sense.get("alt_of"):
            continue
        tags = sense.get("tags", [])
        if any(sub in tag for tag in tags for sub in EXCLUDE_TAG_SUBSTRINGS):
            continue
        glosses = sense.get("glosses") or []
        if not glosses:
            continue
        gloss = clean_gloss(glosses[0])
        if not gloss or gloss.lower().startswith(EXCLUDE_GLOSS_PREFIXES):
            continue
        if LETTER_GLOSS_RE.match(gloss):
            continue
        out.append((pos, gloss))
    return out


def romanizations(entry: dict) -> list[str]:
    return [
        f["form"]
        for f in entry.get("forms", [])
        if f.get("form") and "romanization" in f.get("tags", [])
    ]


def walk_descendants(items: list) -> "iter":
    """Yield every descendant item, however deeply nested."""
    for item in items:
        if not isinstance(item, dict):
            continue
        yield item
        yield from walk_descendants(item.get("descendants") or [])


BHO_TEXT_RE = re.compile(r"Bhojpuri:\s*([^\s(,;]+)")


def bhojpuri_descendants(entry: dict) -> list[tuple[str, str | None]]:
    """(bho_word, roman|None) pairs from an entry's Descendants section.

    Handles both the structured item shape ({lang, lang_code, word, ...},
    with per-script children nested under a Bhojpuri container) and the
    older text-based shape ({depth, text}).
    """
    found = []
    for item in walk_descendants(entry.get("descendants") or []):
        word = item.get("word")
        if word and (item.get("lang") == "Bhojpuri" or item.get("lang_code") in ("bh", "bho")):
            found.append((unicodedata.normalize("NFC", word), item.get("roman")))
        text = item.get("text")
        if text and "Bhojpuri" in text:
            for m in BHO_TEXT_RE.finditer(text):
                found.append((unicodedata.normalize("NFC", m.group(1)), None))
    return found


def make_entry(word: str, senses: list[dict], tags: list[str],
               translit: list[str], url_word: str) -> dict:
    return {
        "word": word,
        "lang": "bho",
        "script": detect_script(word),
        "translit": list(dict.fromkeys(translit)),
        "phones": [],
        "tags": tags,
        "senses": senses,
        "source": SOURCE,
        "source_url": source_url(url_word),
        "license": LICENSE,
    }


def main() -> None:
    ensure_dump()
    OUT.parent.mkdir(parents=True, exist_ok=True)

    print(f"Counting Devanagari tokens in {CORPUS.name} …", file=sys.stderr)
    freq = build_freq_table()
    print(f"  {len(freq)} distinct tokens, {sum(freq.values())} total", file=sys.stderr)

    # Pass over the dump: group senses/romanizations per headword and
    # collect explicit Bhojpuri descendants.
    by_word: dict[str, dict] = {}  # word -> {"senses": [(pos, gloss)], "roms": []}
    descendants: dict[str, dict] = {}  # bho word -> {"senses": [...], "roms": [], "parent": str}
    n_lines = n_kaithi_skipped = 0
    with gzip.open(DUMP, "rt", encoding="utf-8") as f:
        for line in f:
            n_lines += 1
            entry = json.loads(line)
            word = unicodedata.normalize("NFC", entry.get("word", ""))
            if not word:
                continue
            agg = by_word.setdefault(word, {"senses": [], "roms": []})
            agg["senses"] += real_senses(entry)
            agg["roms"] += romanizations(entry)

            for bho_word, roman in bhojpuri_descendants(entry):
                if not devanagari_dominant(bho_word):
                    n_kaithi_skipped += 1  # Kaithi-script variants etc.
                    continue
                parent_senses = real_senses(entry)[:2]
                if not parent_senses:
                    continue
                d = descendants.setdefault(
                    bho_word, {"senses": [], "roms": [], "parent": word})
                for pos, gloss in parent_senses:
                    d["senses"].append((pos, f"{gloss} (cf. Hindi {word})"))
                if roman:
                    d["roms"].append(roman)

    print(f"  read {n_lines} dump lines, {len(by_word)} distinct headwords",
          file=sys.stderr)

    def dedup_senses(pairs: list[tuple[str, str]], cap: int) -> list[dict]:
        return [
            {"pos": pos, "gloss": gloss, "examples": []}
            for pos, gloss in dict.fromkeys(pairs).keys()
        ][:cap]

    # Harvest (a): descendant entries.
    entries: dict[str, dict] = {}
    for bho_word, d in sorted(descendants.items()):
        entries[bho_word] = make_entry(
            bho_word, dedup_senses(d["senses"], 4), ["src:hi-descendant"],
            d["roms"], d["parent"])
    n_descendant = len(entries)

    # Harvest (b): corpus-attested shared vocabulary.
    n_cognate = 0
    review_entries: list[dict] = []
    stoplist_excluded: list[tuple[int, str]] = []
    for word, agg in sorted(by_word.items()):
        if " " in word or not devanagari_dominant(word):
            continue
        n = freq.get(word, 0)
        if n < FREQ_REVIEW:
            continue
        if word in STOPLIST:
            stoplist_excluded.append((n, word))
            continue
        senses = dedup_senses(agg["senses"], 3)
        if not senses:
            continue
        if word in entries:  # merge onto the descendant entry, its glosses first
            e = entries[word]
            have = {(s["pos"], s["gloss"]) for s in e["senses"]}
            e["senses"] += [s for s in senses if (s["pos"], s["gloss"]) not in have]
            e["tags"].append("src:hi-cognate")
            e["translit"] = list(dict.fromkeys(e["translit"] + agg["roms"]))
            n_cognate += 1
        elif n >= FREQ_MAIN:
            entries[word] = make_entry(word, senses, ["src:hi-cognate"],
                                       agg["roms"], word)
            n_cognate += 1
        else:  # 8..19: borderline, for human review only
            review_entries.append(make_entry(word, senses, ["src:hi-cognate"],
                                             agg["roms"], word))

    with OUT.open("w", encoding="utf-8") as f:
        for e in sorted(entries.values(), key=lambda e: e["word"]):
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    with OUT_REVIEW.open("w", encoding="utf-8") as f:
        for e in review_entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    print(f"(a) descendants: {n_descendant} entries "
          f"({n_kaithi_skipped} non-Devanagari script variants skipped)",
          file=sys.stderr)
    print(f"(b) corpus-attested cognates: {n_cognate} entries "
          f"(freq >= {FREQ_MAIN}; incl. merges into descendant entries)",
          file=sys.stderr)
    print(f"Wrote {len(entries)} entries -> {OUT}", file=sys.stderr)
    print(f"Wrote {len(review_entries)} borderline entries "
          f"(freq {FREQ_REVIEW}-{FREQ_MAIN - 1}) -> {OUT_REVIEW}", file=sys.stderr)
    top = sorted(stoplist_excluded, reverse=True)[:10]
    print("Top stoplist exclusions by bho-corpus freq:", file=sys.stderr)
    for n, w in top:
        print(f"  {w}\t{n}", file=sys.stderr)


if __name__ == "__main__":
    main()
