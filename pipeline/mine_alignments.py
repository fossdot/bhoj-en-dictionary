#!/usr/bin/env python3
"""Mine a bho→en lexicon from professionally translated parallel corpora
(NLLB-Seed + NLLB-MD) via IBM Model 1 EM word alignment, run in both
directions, and emit canonical JSONL entries (data/canonical/aligned-bho.jsonl).

A (bho_word, en_word) pair is harvested when it co-occurs in >= 3 sentence
pairs and the geometric mean of p(en|bho) and p(bho|en) is >= 0.30; pairs
scoring 0.20-0.30 land in data/canonical/aligned-bho-review.jsonl instead.

Usage:
    python3 pipeline/mine_alignments.py
"""

import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PARALLEL = BASE / "data" / "corpus" / "parallel"
OUT = BASE / "data" / "canonical" / "aligned-bho.jsonl"
OUT_REVIEW = BASE / "data" / "canonical" / "aligned-bho-review.jsonl"

# Professionally translated sets only — no EVAL-ONLY / -NC files.
INPUT_FILES = [
    "nllb-seed.jsonl",
    "nllb-md-chat-train.jsonl",
    "nllb-md-chat-valid.jsonl",
    "nllb-md-news-train.jsonl",
    "nllb-md-news-valid.jsonl",
    "nllb-md-health-train.jsonl",
    "nllb-md-health-valid.jsonl",
]

EM_ITERATIONS = 10
NULL = 0  # id 0 is reserved for the NULL token in both vocabularies

MIN_COOC = 3
MIN_SCORE = 0.30
MIN_REVIEW_SCORE = 0.20

EN_STOPLIST = frozenset(
    "the a an of to and in is was were for on it he she they that this with "
    "as at be are am i you we not have has had but or from by will would can "
    "could do does did my your his her its our their".split()
)

# English side: lowercase, strip punctuation (hyphens survive inside words),
# split on whitespace. \w keeps accented letters (Sühl) whole.
EN_PUNCT_RE = re.compile(r"[^\w\s-]")
# Bhojpuri tokens: runs of Devanagari (danda/double danda/abbrev sign excluded).
DEVA_TOKEN_RE = re.compile(r"[ऀ-ॿ]+")
DEVA_PUNCT = str.maketrans("", "", "।॥॰")
DEVA_CHAR_RE = re.compile(r"[ऀ-ॿ]")


def tokenize_en(text: str) -> list[str]:
    toks = (t.strip("-_") for t in EN_PUNCT_RE.sub(" ", text.lower()).split())
    return [t for t in toks if t]


def tokenize_bho(text: str) -> list[str]:
    toks = (t.translate(DEVA_PUNCT) for t in DEVA_TOKEN_RE.findall(text))
    return [t for t in toks if t]


def good_en(tok: str) -> bool:
    return (
        len(tok) >= 2
        and tok not in EN_STOPLIST
        and tok.replace("-", "").isalpha()
    )


def good_bho(tok: str) -> bool:
    if len(tok) < 2 or tok.isdigit():
        return False
    deva = len(DEVA_CHAR_RE.findall(tok))
    return deva / len(tok) >= 0.8


def load_corpus() -> list[tuple[list[str], list[str]]]:
    pairs = []
    for name in INPUT_FILES:
        n = 0
        with (PARALLEL / name).open() as f:
            for line in f:
                row = json.loads(line)
                bho, en = tokenize_bho(row["bho"]), tokenize_en(row["en"])
                if bho and en:
                    pairs.append((bho, en))
                    n += 1
        print(f"  {name}: {n} usable pairs", file=sys.stderr)
    return pairs


def train_model1(
    corpus: list[tuple[list[int], list[int]]], n_src: int
) -> dict[int, dict[int, float]]:
    """IBM Model 1 EM: returns t[src][tgt] = p(tgt | src).

    Each corpus item is (src_ids, tgt_ids); a NULL token (id 0) is prepended
    to every source sentence. Sentences are compressed to (token, count)
    lists so repeated tokens cost one inner-loop pass.
    """
    compressed = [
        (list(Counter([NULL] + src).items()), list(Counter(tgt).items()))
        for src, tgt in corpus
    ]
    uniform = 1.0 / n_src
    t: dict[int, dict[int, float]] = {}
    for it in range(EM_ITERATIONS):
        counts: dict[int, dict[int, float]] = defaultdict(dict)
        totals: dict[int, float] = defaultdict(float)
        loglik = 0.0
        for src_c, tgt_c in compressed:
            for f, cf in tgt_c:
                z = 0.0
                for e, _ in src_c:
                    z += t.get(e, {}).get(f, uniform)
                loglik += cf * math.log(z)
                for e, ce in src_c:
                    p = t.get(e, {}).get(f, uniform)
                    c = cf * ce * p / z
                    row = counts[e]
                    row[f] = row.get(f, 0.0) + c
                    totals[e] += c
        t = {
            e: {f: c / totals[e] for f, c in row.items() if c / totals[e] > 1e-7}
            for e, row in counts.items()
        }
        print(f"    iter {it + 1}/{EM_ITERATIONS} loglik={loglik:.0f}", file=sys.stderr)
    return t


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)

    print("Loading corpus …", file=sys.stderr)
    corpus = load_corpus()
    print(f"  total: {len(corpus)} sentence pairs", file=sys.stderr)

    # Integer ids (0 = NULL) keep the EM tables light.
    bho_ids: dict[str, int] = {}
    en_ids: dict[str, int] = {}
    ids = lambda vocab, toks: [vocab.setdefault(w, len(vocab) + 1) for w in toks]
    encoded = [(ids(bho_ids, b), ids(en_ids, e)) for b, e in corpus]

    print("Training IBM Model 1, bho→en (t[bho][en] = p(en|bho)) …", file=sys.stderr)
    t_en_given_bho = train_model1(encoded, len(bho_ids) + 1)
    print("Training IBM Model 1, en→bho (t[en][bho] = p(bho|en)) …", file=sys.stderr)
    t_bho_given_en = train_model1([(e, b) for b, e in encoded], len(en_ids) + 1)

    bho_word = {i: w for w, i in bho_ids.items()}
    en_word = {i: w for w, i in en_ids.items()}

    # Candidate pairs: both directions agree above the review floor, tokens pass filters.
    candidates: dict[tuple[int, int], float] = {}
    for b, row in t_en_given_bho.items():
        if b == NULL or not good_bho(bho_word[b]):
            continue
        for e, p_e_b in row.items():
            p_b_e = t_bho_given_en.get(e, {}).get(b, 0.0)
            score = math.sqrt(p_e_b * p_b_e)
            if score >= MIN_REVIEW_SCORE and good_en(en_word[e]):
                candidates[(b, e)] = score

    # Sentence-level co-occurrence counts, only for candidate pairs.
    cooc: dict[tuple[int, int], int] = defaultdict(int)
    cand_bho = {b for b, _ in candidates}
    for b_sent, e_sent in encoded:
        b_set = set(b_sent) & cand_bho
        e_set = set(e_sent)
        for b in b_set:
            for e in e_set:
                if (b, e) in candidates:
                    cooc[(b, e)] += 1

    harvested: dict[int, list[tuple[int, float]]] = defaultdict(list)
    borderline: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for (b, e), score in candidates.items():
        if cooc[(b, e)] < MIN_COOC:
            continue
        (harvested if score >= MIN_SCORE else borderline)[b].append((e, score))

    def to_entry(b: int, pairs: list[tuple[int, float]]) -> dict:
        top = sorted(pairs, key=lambda x: -x[1])[:3]
        return {
            "word": bho_word[b],
            "lang": "bho",
            "script": "Deva",
            "translit": [],
            "phones": [],
            "tags": ["src:aligned"],
            "senses": [
                {"pos": "", "gloss": en_word[e], "examples": []} for e, _ in top
            ],
            "align_scores": {en_word[e]: round(s, 3) for e, s in top},
            "source": "IBM-1 word alignment over NLLB-Seed/MD professional translations",
            "source_url": "https://github.com/facebookresearch/flores",
            "license": "CC-BY-SA 4.0 (derived)",
        }

    entries = [to_entry(b, ps) for b, ps in sorted(harvested.items(), key=lambda kv: bho_word[kv[0]])]
    review = [to_entry(b, ps) for b, ps in sorted(borderline.items(), key=lambda kv: bho_word[kv[0]])]

    with OUT.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    with OUT_REVIEW.open("w") as f:
        for entry in review:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    kept = [s for e in entries for s in e["align_scores"].values()]
    hi = sum(1 for s in kept if s >= 0.5)
    mid = sum(1 for s in kept if 0.4 <= s < 0.5)
    lo = sum(1 for s in kept if s < 0.4)
    print(f"Wrote {len(entries)} entries ({len(kept)} pairs) → {OUT}", file=sys.stderr)
    print(f"  score >=0.5: {hi}   0.4-0.5: {mid}   0.3-0.4: {lo}", file=sys.stderr)
    print(f"Wrote {len(review)} borderline entries → {OUT_REVIEW}", file=sys.stderr)


if __name__ == "__main__":
    main()
