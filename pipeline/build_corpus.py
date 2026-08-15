#!/usr/bin/env python3
"""Normalize all downloaded parallel/monolingual sources into data/corpus/.

Outputs
  data/corpus/parallel/*.jsonl   {"bho": ..., "en": ..., "source": ..., "license": ...}
  data/corpus/mono/*.txt         one sentence/paragraph per line
  data/corpus/STATS.md           per-source line counts

Sources handled (whatever is present under data/raw/ is used):
  flores200      CC-BY-SA 4.0     — kept as EVAL ONLY (dev/devtest); never train on these
  opus/tatoeba   CC-BY 2.0 FR
  opus/wikimedia CC-BY-SA 3.0
  opus/nllb      ODC-BY           — mined, tiered by LASER score (high ≥1.15, med ≥1.10)
  bho-resources  CC-BY-NC-SA 4.0  — BHLTR (JNU); NON-COMMERCIAL, kept in separate files
  UD_Bhojpuri-BHTB CC-BY-SA 4.0   — treebank sentences → mono

Usage:
    python3 pipeline/build_corpus.py
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PAR = ROOT / "data" / "corpus" / "parallel"
MONO = ROOT / "data" / "corpus" / "mono"

stats: list[tuple[str, int, str]] = []  # (name, lines, license)


def write_pairs(name: str, pairs, license_: str, extra=None) -> None:
    path = PAR / f"{name}.jsonl"
    n = 0
    with path.open("w") as f:
        for bho, en, *rest in pairs:
            bho, en = bho.strip(), en.strip()
            if not bho or not en:
                continue
            row = {"bho": bho, "en": en, "source": name, "license": license_}
            if extra and rest:
                row[extra] = rest[0]
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    stats.append((f"parallel/{name}", n, license_))
    print(f"  {name}: {n} pairs", file=sys.stderr)


def write_mono(name: str, lines, license_: str) -> None:
    path = MONO / f"{name}.txt"
    seen, kept = set(), []
    for ln in lines:
        ln = re.sub(r"\s+", " ", ln).strip()
        if len(ln) > 3 and ln not in seen:
            seen.add(ln)
            kept.append(ln)
    path.write_text("\n".join(kept) + "\n")
    stats.append((f"mono/{name}", len(kept), license_))
    print(f"  {name}: {len(kept)} lines", file=sys.stderr)


def flores() -> None:
    base = RAW / "flores" / "flores200_dataset"
    if not base.exists():
        return
    for split, ext in (("dev", "dev"), ("devtest", "devtest")):
        bho = (base / split / f"bho_Deva.{ext}").read_text().splitlines()
        en = (base / split / f"eng_Latn.{ext}").read_text().splitlines()
        write_pairs(f"flores200-{split}-EVAL-ONLY", zip(bho, en), "CC-BY-SA 4.0")


def opus_simple(dirname: str, prefix: str, license_: str) -> None:
    d = RAW / "opus" / dirname
    if not d.exists():
        return
    bho = (d / f"{prefix}.bho-en.bho").read_text().splitlines()
    en = (d / f"{prefix}.bho-en.en").read_text().splitlines()
    write_pairs(dirname, zip(bho, en), license_)


def translatewiki() -> None:
    d = RAW / "opus" / "translatewiki"
    if not d.exists():
        return
    bho = (d / "translatewiki.bho-en.bho").read_text().splitlines()
    en = (d / "translatewiki.bho-en.en").read_text().splitlines()
    # UI strings: drop rows with template syntax or placeholders on either side
    bad = re.compile(r"\{\{|\}\}|\$\d|<[a-z/]|&\w+;|^\W*$")
    pairs = [(b, e) for b, e in zip(bho, en) if not bad.search(b) and not bad.search(e)]
    write_pairs("translatewiki", pairs, "CC-BY 3.0 (translatewiki.net)")


def nllb() -> None:
    d = RAW / "opus" / "nllb"
    if not d.exists():
        return
    tiers = {"nllb-high": [], "nllb-med": []}
    with (d / "NLLB.bho-en.bho").open() as fb, (d / "NLLB.bho-en.en").open() as fe, \
         (d / "NLLB.bho-en.scores").open() as fs:
        for b, e, s in zip(fb, fe, fs):
            score = float(s)
            if score >= 1.15:
                tiers["nllb-high"].append((b, e, score))
            elif score >= 1.10:
                tiers["nllb-med"].append((b, e, score))
    for name, rows in tiers.items():
        write_pairs(name, rows, "ODC-BY (NLLB mined)", extra="score")


def bhltr() -> None:
    d = RAW / "bho-resources"
    if not d.exists():
        return
    lic = "CC-BY-NC-SA 4.0 (NON-COMMERCIAL)"
    pc = d / "parallel-corpora"
    for split in ("training", "development"):
        bho = (pc / f"eng--bho.{split}.bho").read_text(errors="replace").splitlines()
        en = (pc / f"eng--bho.{split}.eng").read_text(errors="replace").splitlines()
        if len(bho) != len(en):
            print(f"  [WARN] bhltr {split}: {len(bho)} bho vs {len(en)} en lines — truncating to min", file=sys.stderr)
        write_pairs(f"bhltr-{split}-NC", zip(bho, en), lic)
    mono_file = d / "mono-bho-corpus" / "monolingual-v0.2.bho"
    write_mono("bhltr-mono-NC", mono_file.read_text(errors="replace").splitlines(), lic)


def madlad() -> None:
    import gzip

    for tier in ("clean", "noisy"):
        shard = RAW / "madlad" / f"bho_{tier}_0000.jsonl.gz"
        if not shard.exists():
            continue

        def lines(shard=shard, tier=tier):
            for doc in gzip.open(shard, "rt"):
                # MADLAD stores documents with literal "\n" two-char separators
                for ln in json.loads(doc)["text"].split("\\n"):
                    # the noisy tier needs the Devanagari filter (nav debris, English)
                    if tier == "clean" or len(DEVANAGARI_RE.findall(ln)) > len(ln) * 0.4:
                        yield ln

        write_mono(f"madlad-{tier}", lines(), "ODC-BY (MADLAD-400)")


DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")


def hplt() -> None:
    shard = RAW / "hplt" / "bho_Deva_1.jsonl"
    if not shard.exists():
        return

    def lines():
        for doc in shard.open():
            d = json.loads(doc)
            p = d["prob"]
            if (p[0] if isinstance(p, list) else p) < 0.9:  # language-ID confidence
                continue
            for ln in d["text"].splitlines():
                # drop lines that aren't mostly Devanagari (nav debris, English)
                if len(DEVANAGARI_RE.findall(ln)) > len(ln) * 0.4:
                    yield ln

    write_mono("hplt", lines(), "CC0 (HPLT v2; underlying web text rights vary)")


def ud_bhtb() -> None:
    d = RAW / "UD_Bhojpuri-BHTB"
    if not d.exists():
        return
    sents = []
    for conllu in d.glob("*.conllu"):
        for line in conllu.read_text().splitlines():
            if line.startswith("# text = "):
                sents.append(line[len("# text = "):])
    write_mono("ud-bhtb", sents, "CC-BY-SA 4.0")


def main() -> None:
    PAR.mkdir(parents=True, exist_ok=True)
    MONO.mkdir(parents=True, exist_ok=True)
    flores()
    opus_simple("tatoeba", "Tatoeba", "CC-BY 2.0 FR")
    opus_simple("wikimedia", "wikimedia", "CC-BY-SA 3.0")
    translatewiki()
    nllb()
    bhltr()
    madlad()
    hplt()
    ud_bhtb()

    # bhwiki.txt is produced by extract_bhwiki.py — include it in the stats
    bhwiki = MONO / "bhwiki.txt"
    if bhwiki.exists():
        n = sum(1 for ln in bhwiki.open() if ln.strip())
        stats.append(("mono/bhwiki", n, "CC-BY-SA 4.0"))

    # cross-source exact-line dedup (web crawls overlap; HPLT mirrors Wikipedia).
    # priority order: curated first, crawls after — first occurrence wins.
    # excludes -NC files so the aggregate stays commercial-safe.
    seen: set[str] = set()
    n = 0
    with (MONO / "all-dedup.txt").open("w") as out:
        for name in ("bhwiki", "ud-bhtb", "hplt", "madlad-clean", "madlad-noisy"):
            f = MONO / f"{name}.txt"
            if not f.exists():
                continue
            for ln in f.open():
                ln = ln.strip()
                if ln and ln not in seen:
                    seen.add(ln)
                    out.write(ln + "\n")
                    n += 1
    stats.append(("mono/all-dedup", n, "aggregate, commercial-safe sources only"))
    print(f"  all-dedup: {n} lines", file=sys.stderr)

    lines = ["# Corpus stats", "", "| file | lines | license |", "|---|---:|---|"]
    lines += [f"| {n} | {c} | {l} |" for n, c, l in stats]
    (ROOT / "data" / "corpus" / "STATS.md").write_text("\n".join(lines) + "\n")
    print("wrote data/corpus/STATS.md", file=sys.stderr)


if __name__ == "__main__":
    main()
