# bhoj — Bhojpuri dictionary + LLM data pipeline

A Bhojpuri→English dictionary built on [dictpress](https://dict.press)
(Kailash Nadh's dictionary webserver), designed so the same curated data
feeds Bhojpuri LLM development: seed lexicon, parallel sentence pairs, and
instruction-tuning data are generated from one canonical source.

## Architecture

```
sources (Wiktionary, …)
      │  pipeline/fetch_*.py
      ▼
data/canonical/*.jsonl        ← single source of truth (one entry per line)
      │                                │
      │ pipeline/to_dictpress.py       │ pipeline/to_training.py
      ▼                                ▼
dictpress/import.csv          data/training/
  → public dictionary site      ├─ lexicon.tsv        bho ⇄ en word pairs
                                ├─ parallel.jsonl     bho ⇄ en sentence pairs
                                └─ instructions.jsonl chat-format SFT data
```

The canonical JSONL is authoritative; both the dictionary site and the
training exports are regenerated from it, so they never diverge.

## Canonical entry schema

```json
{
  "word": "अगुआ",
  "lang": "bho",
  "script": "Deva",              // Deva | Kthi (Kaithi) | Latn
  "translit": ["aguā"],
  "phones": ["/ə.ɡu.aː/"],
  "tags": ["gender:m"],
  "senses": [
    {
      "pos": "noun",
      "gloss": "leader, head",   // English gloss → bho→en direction
      "examples": [{"bho": "…", "en": "…", "translit": "…"}]
    }
  ],
  "source": "en.wiktionary.org",
  "source_url": "https://en.wiktionary.org/wiki/अगुआ#Bhojpuri",
  "license": "CC BY-SA 4.0"
}
```

Usage examples are first-class: they're the highest-value data for LLM
training (parallel text), even though a dictionary UI treats them as
decoration.

## Quick start

```sh
# 1. Fetch sources → canonical JSONL (cached; --refresh to refetch)
python3 pipeline/fetch_wiktionary.py

# 2. Generate dictpress import CSV + LLM training exports
python3 pipeline/to_dictpress.py data/canonical/*.jsonl > dictpress/import.csv
python3 pipeline/to_training.py data/canonical/*.jsonl

# 3. Set up + run the dictionary site (dictpress v5 ships Linux binaries → Docker on macOS)
cd dictpress
docker run --rm -v "$PWD:/work" -w /work/app alpine \
  ./dictpress --config ../config.toml --db ../data.db install
docker run --rm -v "$PWD:/work" -w /work/app alpine \
  ./dictpress --config ../config.toml --db ../data.db import --file ../import.csv
docker run -d --name bhoj-dict -p 9000:9000 -v "$PWD:/work" -w /work/app alpine \
  ./dictpress --config ../config.toml --db ../data.db --site ../site
```

(or just `make dict`; `dictpress/site/` is the committed theme — the upstream
default with Bhoj branding in `lang.json`)

Then open <http://localhost:9000> (site) or <http://localhost:9000/admin>
(admin, credentials in `dictpress/config.toml` — change them). Search
supports romanized phonetic lookup: `agua` finds अगुआ, via the bundled
IndicPhone Devanagari tokenizer.

`dictpress/app/` (binary + default site theme) is not committed; download
from [dictpress releases](https://github.com/knadh/dictpress/releases)
(v5.0.0-rc5, `aarch64-unknown-linux-musl` for Apple Silicon Docker).

## Data sources

### Dictionary (→ `data/canonical/`, all in dictpress)

| Source | Yield | License |
|---|---|---|
| [en-Wiktionary bho lemmas](https://en.wiktionary.org/wiki/Category:Bhojpuri_lemmas) | 421 entries, 477 senses, 32 example pairs | CC BY-SA 4.0 |
| en-Wiktionary translation tables (711 pages mined) | 742 bho words, 768 pairs | CC BY-SA 4.0 |
| [GATITOS](https://huggingface.co/datasets/google/smol) (Google SMOL) | 3,488 headwords, 7,982 pairs — core vocab + phrases | CC BY 4.0 |
| Hindi pivot (kaikki.org Hindi × corpus-attested, freq ≥ 20) | 8,907 headwords, tagged `src:hi-cognate` | CC BY-SA 4.0 |
| IBM-1 alignment over NLLB-Seed/MD pro translations | 4,097 headwords, tagged `src:aligned` | CC BY-SA 4.0 (derived) |
| bhwiki interlanguage links (≤3 words, no digits) | 8,310 headwords, tagged `src:bhwiki-langlinks` | CC BY-SA 4.0 |
| **merged** | **20,568 headwords, 31,387 definitions** | |

Every machine-derived source went through a two-lens judge panel (semantic
correctness + lexicographic quality) on random samples before import — all
passed at 100% on samples; borderline entries live in `*-review.jsonl` files
that are **not** imported (alignment scores 0.20–0.30: 1,029; cognate
freq 8–19: 1,853). Entries carry `src:*` tags for later per-source review.

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
15k professionally translated); 133k-example SFT bundle (`sft.jsonl`),
163k with NC sources (`sft-nc.jsonl`). Language audit in
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

## Layout

```
pipeline/
  fetch_wiktionary.py               en-Wiktionary bho lemma pages → canonical JSONL
  fetch_wiktionary_translations.py  en-Wiktionary translation tables → canonical JSONL
  extract_bhwiki.py                 bhwiki XML dump → data/corpus/mono/bhwiki.txt
  build_corpus.py                   all raw sources → data/corpus/{parallel,mono} + STATS.md
  to_dictpress.py                   canonical JSONL (merged by headword) → dictpress import CSV
  to_training.py                    canonical JSONL → lexicon.tsv / parallel.jsonl / instructions.jsonl
  assemble_sft.py                   instructions + corpus parallel → sft.jsonl (--include-nc → sft-nc.jsonl)
data/
  raw/                  raw source pulls (gitignored; refetch via pipeline + URLs in scripts)
  canonical/            canonical JSONL, one file per source
  corpus/               normalized corpora (gitignored; rebuild with build_corpus.py)
  training/             LLM exports (large sft*.jsonl gitignored)
dictpress/
  config.toml           dictpress v5 config (bhojpuri → english)
  import.csv            generated import file
  app/                  dictpress binary + theme (gitignored, see Quick start)
```

## Rebuild everything

```sh
make fetch   # Wiktionary + GATITOS → canonical JSONL
make data    # corpus + dictionary CSV + training exports (needs data/raw/ downloads)
make dict    # fresh DB + import + restart the dictpress container
```

(See the Makefile for the underlying `pipeline/*.py` commands; raw-source
download URLs are documented in each fetcher/processor script.)

## Evaluation

FLORES-200 bho files are the benchmark — never train on them. See
`eval/README.md` for the protocol and `eval/score.py` for a dependency-free
chrF2 scorer.
