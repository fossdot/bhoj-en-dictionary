# Data sources, quality, and licensing

### Dictionary (→ `data/canonical/`, all in dictpress)

| Source | Yield | License |
|---|---|---|
| [en-Wiktionary bho lemmas](https://en.wiktionary.org/wiki/Category:Bhojpuri_lemmas) | 421 entries, 477 senses, 32 example pairs | CC BY-SA 4.0 |
| en-Wiktionary translation tables (711 pages mined) | 742 bho words, 768 pairs | CC BY-SA 4.0 |
| [GATITOS](https://huggingface.co/datasets/google/smol) (Google SMOL) | 3,488 headwords, 7,982 pairs — core vocab + phrases | CC BY 4.0 |
| Hindi pivot (kaikki.org Hindi × corpus-attested, freq ≥ 20) | 8,907 headwords, tagged `src:hi-cognate` | CC BY-SA 4.0 |
| IBM-1 alignment over NLLB-Seed/MD pro translations | 4,097 headwords, tagged `src:aligned` | CC BY-SA 4.0 (derived) |
| bhwiki interlanguage links (≤3 words, no digits) | 8,310 headwords, tagged `src:bhwiki-langlinks` | CC BY-SA 4.0 |
| **merged, after cleaning** | **20,254 headwords, 30,432 definitions** | |

Every machine-derived source went through a two-lens judge panel (semantic
correctness + lexicographic quality) on random samples before import.
Borderline candidates live in `*-review.jsonl` files that are **not**
imported (alignment scores 0.20–0.30: 1,029; cognate freq 8–19: 1,853).
Entries carry `src:*` tags for per-source review.

**Full quality sweep** (`data/cleaning/`): every one of the 25,859 entry-senses
was then read by a reviewer agent under a source-specific rubric, and every
proposed change independently verified before application — 1,007 mechanical
fixes (`pipeline/clean_canonical.py`) plus 2,145 reviewed changes
(1,642 gloss corrections, 336 sense deletions, 111 entry deletions, 56 tags).
62 proposed deletions were **rejected** by verification to protect regional
vocabulary. Audit trail: `mechanical-log.jsonl`, `all-findings.jsonl`,
`verdicts.jsonl`, `applied-log.jsonl`.

### Corpus (→ `data/corpus/`, see `STATS.md` for exact counts)

| Source | Yield | License |
|---|---|---|
| [HPLT v2](https://hplt-project.org) `bho_Deva` | 6.6M words (prob≥0.9 + Devanagari filter) | CC0 (web text) |
| [FineWeb-2](https://huggingface.co/datasets/HuggingFaceFW/fineweb-2) `bho_Deva` | 7.3M words, best-filtered crawl | ODC-BY |
| [finepdfs](https://huggingface.co/datasets/HuggingFaceFW/finepdfs) `bho_Deva` | 4.0M words of long-form PDFs (matra-order repaired by `extract_parquet.py`) | ODC-BY |
| [MADLAD-400](https://huggingface.co/datasets/allenai/MADLAD-400) `bho` clean+noisy | 2.7M + 6.9M words ("noisy" tier is decent bho journalism) | ODC-BY |
| [Bhojpuri Wikipedia](https://bh.wikipedia.org) dump | 1.19M words | CC BY-SA 4.0 |
| [VarDial 2018 ILI](https://github.com/kmi-linguistics/vardial2018) | 18.8k literature sentences (full 5-lang set = LID training data) | Apache-2.0 |
| [NLLB-Seed](https://github.com/facebookresearch/flores/tree/main/nllb_seed) | 6,193 professionally translated pairs (training-grade) | CC BY-SA 4.0 |
| [NLLB-MD](https://github.com/facebookresearch/flores/tree/main/nllb_md) chat/news/health | 8,809 pro pairs (test splits kept EVAL-ONLY) | CC BY-SA 4.0 |
| [OPUS NLLB](https://opus.nlpl.eu) mined bho–en bitext | 8.7k pairs @LASER≥1.15, 121k @≥1.10 (of 2.43M raw) | ODC-BY |
| [FLORES-200](https://github.com/facebookresearch/flores) dev+devtest | 2,009 pro-translated pairs — **EVAL ONLY, never train** | CC BY-SA 4.0 |
| OPUS wikimedia / translatewiki / Tatoeba | 1,982 / 2,243 / 42 pairs | CC BY-SA / CC BY / CC BY |
| [BHLTR (JNU)](https://github.com/shashwatup9k/bho-resources) | 29.5k parallel + 43k mono lines — kept in `-NC` files | CC BY-**NC**-SA ⚠ |
| [UD Bhojpuri BHTB](https://github.com/UniversalDependencies/UD_Bhojpuri-BHTB) | 268 sentences (+POS trees) | CC BY-SA 4.0 |

**Bottom line: `mono/all-dedup.txt` = 19.1M words / 560k lines (~28M tokens)
of deduplicated, commercial-safe Bhojpuri text; ~180k parallel pairs (incl.
15k professionally translated); 149k-example SFT bundle (`sft.jsonl`),
179k with NC sources (`sft-nc.jsonl`). Language audit in
`data/corpus/QUALITY.md` (`pipeline/audit_language.py`).**

Dead ends checked so far: kaikki.org (no bho extract), IndicCorpV2/Sangraha/BPCC
(bho not a scheduled language, excluded), eBible (no open bho scripture),
OLDI-seed (no bho), SMOL doc/sent (no bho — only GATITOS), HPLT bitexts (none),
Leipzig + StoryWeaver (bot-walled), Wikimedia incubator Wt/bho (~30 stubs),
Wikidata lexemes (30, subset of Wiktionary), CC-100 (no bh split online),
FLEURS/CommonVoice/XLSum/PMIndia (no bho).

### Public-domain OCR leads (archive.org, future work)

The deepest untapped lexical sources are 19th-century and out of copyright.
OCRing 1880s Devanagari is a project of its own, but the payoff is thousands
of entries + parallel specimens:

- `acomparativedic00griegoog` — Grierson, *A Comparative Dictionary of the
  Bihārī Language* (1885)
- `sevengrammarsofd04grie` — Grierson, *Seven Grammars of the Dialects and
  Subdialects of the Bihárí Language* (1883–87; includes Bhojpuri vocabulary)
- `in.ernet.dli.2015.32104` — *Linguistic Survey of India* Vol. 5 Pt. 2
  (1903; Bhojpuri specimen passages **with aligned English translations**)
- `hindustani-proverbs-dictionary-marwari-punjabi-maggah-bhojpuri-tirhuti` —
  Fallon, *A Dictionary of Hindustani Proverbs* (1886; incl. Bhojpuri)

Notes for LLM work:

- Realistic model path: continued pretraining / fine-tuning of a
  Hindi-strong open base (Devanagari, high lexical overlap), not
  pretraining from scratch.
- FLORES-200 files are named `*-EVAL-ONLY` for a reason: they're the
  benchmark. Keep them out of every training set.
- NLLB `bho` side and web crawls carry Awadhi/Hindi/Magahi contamination;
  the LASER-score tiers and Devanagari filters here are first-pass cleanup,
  not the last word.

## Licensing

This repo mixes three kinds of material, and they are not under one licence:

- **Dictionary data** (`data/canonical/`) — derived from open sources, each
  entry carrying its own `license` field: CC BY-SA 4.0 (Wiktionary, bhwiki,
  NLLB-Seed/MD), CC BY 4.0 (GATITOS). Attribution and share-alike obligations
  follow the entries; keep the `source`/`license` fields when redistributing.
- **Corpus** (`data/corpus/`, not committed) — per-source licences listed in
  `data/corpus/STATS.md`. Anything in a `*-NC` file is **non-commercial only**
  (BHLTR/JNU, CC BY-NC-SA); `sft.jsonl` excludes those, `sft-nc.jsonl` does not.
- **Site theme** (`dictpress/site/`) — a modified copy of the dictpress default
  theme, which is **AGPL-3.0** (see `dictpress/app/LICENSE` after downloading
  the release).

The pipeline code (`pipeline/`, `eval/`) has no licence file yet — without one
it is "all rights reserved" by default, so pick one before expecting outside
contributions to code.
