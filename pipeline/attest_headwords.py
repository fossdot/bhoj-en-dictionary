#!/usr/bin/env python3
"""Check every headword against human-curated Bhojpuri sources.

The earlier context scoring leaned on `all-dedup-lid-bho.txt`, which is web
crawl sorted by a machine classifier — it answers "does this look Bhojpuri"
and inherits whatever Hindi the crawl carried in. This asks a stricter
question: has a person who was writing or annotating Bhojpuri ever used
this word?

Only sources that are Bhojpuri by editorial decision count here.

  gold      hand-annotated lexica: the UD Bhojpuri treebank (lemmas and
            forms), the POS-tagged BHLTR corpus, Wikidata bho lexemes,
            en-Wiktionary's Bhojpuri section, GATITOS
  authored  text written or professionally translated as Bhojpuri:
            Bhojpuri Wikipedia, the BHLTR monolingual and parallel
            corpora, VarDial's gold bho set, NLLB-Seed / NLLB-MD

Deliberately excluded: madlad, hplt, fineweb2, finepdfs (crawl, machine
labelled) and FLORES (the benchmark — letting it decide what stays in the
dictionary would leak the eval into the training data).

Usage:
    python3 pipeline/attest_headwords.py
"""

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANON = ROOT / "data" / "canonical"
RAW = ROOT / "data" / "raw"
MONO = ROOT / "data" / "corpus" / "mono"
PAR = ROOT / "data" / "corpus" / "parallel"
OUT = ROOT / "data" / "cleaning" / "attestation.jsonl"
REPORT = ROOT / "data" / "cleaning" / "ATTESTATION.md"

TOKEN = re.compile(r"[ऀ-ॿ\U00011080-\U000110CF]+")
KAITHI = re.compile(r"[\U00011080-\U000110CF]")


def nfc(s):
    return unicodedata.normalize("NFC", str(s))


def toks(text):
    return set(TOKEN.findall(nfc(text)))


def from_lines(path, limit=None):
    v = set()
    if not path.exists():
        return v
    with path.open(encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if limit and i >= limit:
                break
            v |= toks(line)
    return v


def from_conllu(path):
    """Surface forms AND lemmas — a lemma is the dictionary form."""
    v = set()
    if not path.exists():
        return v
    for line in path.open(encoding="utf-8", errors="replace"):
        if line.startswith("#") or not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) > 2:
            v |= toks(cols[1]) | toks(cols[2])
    return v


def from_jsonl_field(path, field="bho"):
    v = set()
    if not path.exists():
        return v
    for line in path.open(encoding="utf-8", errors="replace"):
        line = line.strip()
        if line:
            try:
                v |= toks(json.loads(line).get(field, ""))
            except json.JSONDecodeError:
                continue
    return v


def build_sources():
    src = {}
    bres = RAW / "bho-resources"

    # --- gold: hand-annotated lexical resources -------------------------
    src["ud-treebank"] = ("gold", from_conllu(
        RAW / "UD_Bhojpuri-BHTB" / "bho_bhtb-ud-test.conllu"))
    src["pos-tagged"] = ("gold", from_lines(
        bres / "mono-bho-corpus" / "pos-annotated" / "pos-tagged.bho"))

    wd = set()
    p = RAW / "wikidata-lexemes-bho.csv"
    if p.exists():
        for row in csv.DictReader(p.open(encoding="utf-8")):
            wd |= toks(row.get("lemma", ""))
    src["wikidata-lexemes"] = ("gold", wd)

    for name, fn in (("wiktionary-bho", "wiktionary-bho.jsonl"),
                     ("wiktionary-translations", "wiktionary-translations-bho.jsonl"),
                     ("gatitos", "gatitos-bho.jsonl")):
        v = set()
        fp = CANON / fn
        if fp.exists():
            for line in fp.open(encoding="utf-8"):
                if line.strip():
                    v |= toks(json.loads(line)["word"])
        src[name] = ("gold", v)

    # --- authored: written or professionally translated as Bhojpuri -----
    src["bhwiki"] = ("authored", from_lines(MONO / "bhwiki.txt"))
    src["vardial-bho"] = ("authored", from_lines(MONO / "vardial-bho.txt"))
    src["bhltr-mono"] = ("authored",
                         from_lines(bres / "mono-bho-corpus" / "monolingual.bho")
                         | from_lines(bres / "mono-bho-corpus" / "monolingual-v0.2.bho"))
    pc = bres / "parallel-corpora"
    src["bhltr-parallel"] = ("authored",
                             from_lines(pc / "eng--bho.training.bho")
                             | from_lines(pc / "eng--bho.development.bho"))
    src["nllb-md"] = ("authored", from_jsonl_field(PAR / "nllb-md-chat-train.jsonl"))
    return src


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop-unattested", action="store_true",
                    help="remove entries no curated Bhojpuri source has")
    args = ap.parse_args()
    src = build_sources()
    print("source vocabularies:", file=sys.stderr)
    for name, (tier, v) in src.items():
        print(f"  {name:20} {tier:9} {len(v):7} types", file=sys.stderr)

    gold = set().union(*(v for t, v in src.values() if t == "gold"))
    authored = set().union(*(v for t, v in src.values() if t == "authored"))

    entries = []
    for path in sorted(CANON.glob("*.jsonl")):
        for line in path.open(encoding="utf-8"):
            if line.strip():
                e = json.loads(line)
                e["_file"] = path.name
                entries.append(e)

    stats = Counter()
    per_file = defaultdict(Counter)
    with OUT.open("w", encoding="utf-8") as fh:
        for e in entries:
            w = nfc(e["word"])
            parts = TOKEN.findall(w)
            # A multi-word headword counts as attested only if every part is.
            def covered(vocab):
                return bool(parts) and all(p in vocab for p in parts)

            hits = sorted(n for n, (t, v) in src.items() if covered(v))
            if KAITHI.search(w) and not covered(gold):
                # Every corpus checked here is Devanagari, so a Kaithi
                # headword can only ever miss. Absence is not evidence.
                level = "kaithi-uncheckable"
                stats[level] += 1
                per_file[e["_file"]][level] += 1
                fh.write(json.dumps({"word": e["word"], "file": e["_file"],
                                     "attestation": level, "sources": hits},
                                    ensure_ascii=False) + "\n")
                continue
            if covered(gold):
                level = "gold"
            elif covered(authored):
                level = "authored"
            else:
                level = "none"
            stats[level] += 1
            per_file[e["_file"]][level] += 1
            fh.write(json.dumps({"word": e["word"], "file": e["_file"],
                                 "attestation": level, "sources": hits},
                                ensure_ascii=False) + "\n")

    total = len(entries)
    lines = [
        "# Headword attestation",
        "",
        "Generated by `pipeline/attest_headwords.py`. Counts only sources that",
        "are Bhojpuri by editorial decision — hand-annotated lexica and text",
        "written or professionally translated as Bhojpuri. Web crawl is excluded",
        "because its `bho` label is a classifier's guess, and FLORES is excluded",
        "to keep the benchmark out of the dictionary.",
        "",
        "| level | entries | share |",
        "|---|---:|---:|",
        f"| `gold` — in a hand-annotated Bhojpuri lexicon | {stats['gold']} | {100*stats['gold']/total:.0f}% |",
        f"| `authored` — used in Bhojpuri-authored text | {stats['authored']} | {100*stats['authored']/total:.0f}% |",
        f"| `none` — no curated Bhojpuri source has it | {stats['none']} | {100*stats['none']/total:.0f}% |",
        f"| `kaithi-uncheckable` — Kaithi script, no Kaithi corpus to check | {stats['kaithi-uncheckable']} | {100*stats['kaithi-uncheckable']/total:.0f}% |",
        "",
        "## Source vocabularies",
        "",
        "| source | tier | types |",
        "|---|---|---:|",
    ]
    for name, (tier, v) in src.items():
        lines.append(f"| `{name}` | {tier} | {len(v)} |")
    lines += ["", "## By canonical file", "",
              "| file | gold | authored | none | kaithi | % unattested |",
              "|---|---:|---:|---:|---:|---:|"]
    for f in sorted(per_file):
        c = per_file[f]
        n = sum(c.values())
        lines.append(f"| `{f}` | {c['gold']} | {c['authored']} | {c['none']} | "
                     f"{c['kaithi-uncheckable']} | {100*c['none']/n:.0f}% |")
    lines.append("")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[8:17]))
    print(f"\nwrote {REPORT} and {OUT}", file=sys.stderr)

    if not args.drop_unattested:
        return

    unattested = {nfc(e["word"]) for e in entries
                  if not (lambda p: p and all(x in gold or x in authored for x in p))(
                      TOKEN.findall(nfc(e["word"])))}
    removed = []
    for path in sorted(CANON.glob("*.jsonl")):
        rows = [e for e in entries if e["_file"] == path.name]
        keep = [e for e in rows if nfc(e["word"]) not in unattested]
        removed += [e for e in rows if nfc(e["word"]) in unattested]
        with path.open("w", encoding="utf-8") as fh:
            for e in keep:
                fh.write(json.dumps({k: v for k, v in e.items()
                                     if not k.startswith("_")},
                                    ensure_ascii=False) + "\n")
    with (ROOT / "data" / "cleaning" / "unattested-removed.jsonl").open(
            "w", encoding="utf-8") as fh:
        for e in removed:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"removed {len(removed)} unattested entries", file=sys.stderr)


if __name__ == "__main__":
    main()
